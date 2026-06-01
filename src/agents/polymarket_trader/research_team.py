"""
Quant research team surfaces for Polymarket ETH/BTC edge work.

This module turns the current replay scorer, performance tracker, and
live inventory scanner into a repeatable research artifact:

1. What edge do we currently measure on ETH/BTC?
2. What does the live market surface actually look like today?
3. Which research tracks should the team prioritize next?
"""

from __future__ import annotations

import argparse
import json
import os
import threading
from collections import defaultdict
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from termcolor import cprint

from .backtest_scorer import BacktestResult, BacktestScorer, ParamSet, ReplayResult
from .config import ExecutionMode, PolymarketCLIConfig, get_config, get_polymarket_cli_config
from .market_scanner import CLIMarketScanner
from .models import CLIMarket
from .performance_tracker import PerformanceTracker


DEFAULT_RESEARCH_DATA_DIRS = [
    "src/data/polymarket_cli",
    "src/data/polymarket_cli_weekly",
    "src/data/polymarket_cli_intraday",
    "src/data/polymarket_cli_daily",
    "src/data/polymarket_trader_daily",
    "src/data/polymarket_trader_weekly",
    "src/data/polymarket_trader_short",
    "src/data/polymarket_trader",
]

MIN_RESEARCH_CANDIDATE_TRADES = 5


@dataclass
class ResearchRole:
    role_id: str
    title: str
    mandate: str
    primary_metrics: List[str]
    deliverable: str


@dataclass
class ResearchPriority:
    code: str
    title: str
    rationale: str
    actions: List[str] = field(default_factory=list)


@dataclass
class ResearchBlocker:
    code: str
    title: str
    evidence: str
    implication: str


class QuantResearchTeam:
    """Build a current-state ETH/BTC edge report plus a research-team manifest."""

    def __init__(
        self,
        config: Optional[PolymarketCLIConfig] = None,
        data_dirs: Optional[List[str]] = None,
        output_dir: Optional[Path] = None,
        scorer: Optional[BacktestScorer] = None,
        scanner_factory: Optional[Callable[[PolymarketCLIConfig], CLIMarketScanner]] = None,
        performance_tracker_cls: Callable[[PolymarketCLIConfig], PerformanceTracker] = PerformanceTracker,
        swarm_health_resolver: Optional[Callable[[PolymarketCLIConfig], Dict[str, Any]]] = None,
        strict_inventory_timeout_seconds: int = 120,
        broad_inventory_timeout_seconds: int = 180,
        skip_inventory: bool = False,
    ):
        self.config = config or get_config()
        self.active_data_dirs = [str(self.config.data_dir)]
        self.data_dirs = self._resolve_data_dirs(data_dirs)
        self.output_dir = Path(output_dir) if output_dir else self.config.data_dir / "research_team"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.scorer = scorer or BacktestScorer(data_dirs=self.active_data_dirs)
        self.archive_scorer = scorer or BacktestScorer(data_dirs=self.data_dirs)
        self.scanner_factory = scanner_factory or (lambda cfg: CLIMarketScanner(config=cfg))
        self.performance_tracker_cls = performance_tracker_cls
        self.swarm_health_resolver = swarm_health_resolver or self._build_swarm_health
        self.strict_inventory_timeout_seconds = max(1, int(strict_inventory_timeout_seconds))
        self.broad_inventory_timeout_seconds = max(1, int(broad_inventory_timeout_seconds))
        self.skip_inventory = bool(skip_inventory)

    def run(self) -> Dict[str, Any]:
        team_manifest = self.build_team_manifest()
        existing_report = self._load_existing_report()
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "config": self._config_summary(),
            "team_manifest": team_manifest,
            "edge_snapshot": {},
            "expiry_policy_snapshot": {},
            "performance_summary": {},
            "calibration_snapshot": {},
            "edge_quality_snapshot": {},
            "edge_timeframe_snapshot": {},
            "market_archetype_snapshot": {},
            "entry_price_snapshot": {},
            "direction_snapshot": {},
            "policy_rescue_snapshot": {},
            "risk_return_snapshot": {},
            "swarm_health": {},
            "runtime_swarm_health": {},
            "inventory_snapshot": {},
            "inventory_diagnostics": {},
            "blockers": [],
            "deployment_verdict": {},
            "symbol_verdicts": {},
            "surviving_patch_snapshot": {},
            "active_edge_snapshot": {},
            "runtime_regime_snapshot": {},
            "priorities": [],
        }

        self._write_json(self.output_dir / "team_manifest.json", team_manifest)

        edge_snapshot = self.measure_edge()
        report["edge_snapshot"] = edge_snapshot
        report["expiry_policy_snapshot"] = edge_snapshot.get("experiment_matrix", {}).get("expiry_policy_snapshot", {})
        self._write_json(self.output_dir / "edge_report.json", report)

        performance_summary = self.performance_tracker_cls(self.config).generate_report()
        report["performance_summary"] = performance_summary
        report["calibration_snapshot"] = self.build_calibration_snapshot(performance_summary)
        report["edge_quality_snapshot"] = self.build_edge_quality_snapshot(performance_summary)
        report["edge_timeframe_snapshot"] = self.build_edge_timeframe_snapshot(performance_summary)
        report["market_archetype_snapshot"] = self.build_market_archetype_snapshot(performance_summary)
        report["entry_price_snapshot"] = self.build_entry_price_snapshot(performance_summary)
        report["direction_snapshot"] = self.build_direction_snapshot(performance_summary)
        report["policy_rescue_snapshot"] = self.build_policy_rescue_snapshot(performance_summary)
        report["risk_return_snapshot"] = self.build_risk_return_snapshot(performance_summary)
        self._write_json(self.output_dir / "edge_report.json", report)

        swarm_health = self.swarm_health_resolver(self.config)
        report["swarm_health"] = swarm_health
        self._write_json(self.output_dir / "edge_report.json", report)

        runtime_swarm_health = self._build_runtime_swarm_health()
        report["runtime_swarm_health"] = runtime_swarm_health
        self._write_json(self.output_dir / "edge_report.json", report)

        inventory_snapshot = self.scan_live_inventory(existing_report=existing_report)
        report["inventory_snapshot"] = inventory_snapshot
        report["inventory_diagnostics"] = self.build_inventory_diagnostics(inventory_snapshot)

        blockers = self.build_blockers(
            edge_snapshot,
            performance_summary,
            runtime_swarm_health,
            inventory_snapshot,
        )
        report["blockers"] = blockers
        report["deployment_verdict"] = self.build_deployment_verdict(
            edge_snapshot,
            performance_summary,
            runtime_swarm_health,
            blockers,
        )
        report["symbol_verdicts"] = self.build_symbol_verdicts(
            edge_snapshot,
            performance_summary,
            runtime_swarm_health,
            report["deployment_verdict"],
        )
        report["surviving_patch_snapshot"] = self.build_surviving_patch_snapshot(
            report["entry_price_snapshot"],
            report["symbol_verdicts"],
        )
        report["active_edge_snapshot"] = self.build_active_edge_snapshot(
            report["edge_snapshot"],
            report["surviving_patch_snapshot"],
        )
        report["runtime_regime_snapshot"] = self.build_runtime_regime_snapshot(
            runtime_swarm_health,
            blockers,
        )

        priorities = self.build_priorities(
            edge_snapshot,
            performance_summary,
            swarm_health,
            runtime_swarm_health,
            inventory_snapshot,
        )
        report["priorities"] = priorities

        self._write_json(self.output_dir / "edge_report.json", report)
        self._write_markdown(self.output_dir / "edge_report.md", report)
        return report

    def build_team_manifest(self) -> Dict[str, Any]:
        roles = [
            ResearchRole(
                role_id="universe_scout",
                title="Universe Scout",
                mandate="Own ETH/BTC market discovery, symbol hygiene, and expiry/volume policy so the bot scans the markets that actually exist.",
                primary_metrics=["strict_tradeable_markets", "broad_tradeable_markets", "low_volume_24h_exclusions"],
                deliverable="A daily inventory snapshot with tradeable counts, filter failures, and search-surface drift notes.",
            ),
            ResearchRole(
                role_id="swarm_calibration_lead",
                title="Swarm Calibration Lead",
                mandate="Own model availability, prompt calibration, abstain behavior, and price-anchored probability estimates.",
                primary_metrics=["successful_model_count", "abstain_rate", "consensus_accuracy", "brier_score"],
                deliverable="A calibration brief showing when the swarm should trade, abstain, or fail fast.",
            ),
            ResearchRole(
                role_id="structural_arb_researcher",
                title="Structural Arb Researcher",
                mandate="Focus only on clean complementary, ladder, and range coherence edges instead of broad low-quality arbitrage.",
                primary_metrics=["arb_holdout_score", "arb_win_rate", "arb_total_pnl"],
                deliverable="A ranked set of structural arbitrage setups with replay evidence and rejection criteria.",
            ),
            ResearchRole(
                role_id="replay_guardian",
                title="Replay Guardian",
                mandate="Own the truthful measurement stack so parameter changes only ship when holdout and trade-count gates pass.",
                primary_metrics=["replay_accepted", "holdout_score", "filtered_trades", "generalization_gap"],
                deliverable="A go or no-go verdict for every proposed alpha change.",
            ),
            ResearchRole(
                role_id="execution_risk_lead",
                title="Execution Risk Lead",
                mandate="Translate measured edge into attended deployment rules, bankroll sizing, and kill-switch thresholds.",
                primary_metrics=["max_drawdown", "profit_factor", "daily_loss_limit", "stale_order_halts"],
                deliverable="The attended micro-cap deployment checklist and escalation rules.",
            ),
        ]

        return {
            "mission": "Measure and improve Polymarket ETH/BTC edge with honest replay, live inventory awareness, and risk-first deployment gates.",
            "active_thesis": "ETH-first, short-horizon markets are the only measured positive lane today; BTC expansion must earn its way back in.",
            "roles": [asdict(role) for role in roles],
            "workstreams": [
                "Preserve and verify ETH-only edge before broadening symbol coverage.",
                "Split market-universe policy between short-horizon ETH up/down inventory and longer-dated ladder/range inventory.",
                "Keep arbitrage strict and structural; do not rely on weak generic price discrepancies.",
                "Use replay holdout and trade-count gates as the acceptance bar for every change.",
            ],
        }

    def measure_edge(self) -> Dict[str, Any]:
        base = ParamSet.from_config(self.config)
        variants = {
            "current_config": base,
            "eth_only": replace(base, allowed_symbols=["ETH"]),
            "btc_only": replace(base, allowed_symbols=["BTC"]),
            "eth_btc": replace(base, allowed_symbols=["ETH", "BTC"]),
            "eth_swarm_only": replace(base, allowed_symbols=["ETH"], allow_arb=False, allow_swarm=True),
            "btc_swarm_only": replace(base, allowed_symbols=["BTC"], allow_arb=False, allow_swarm=True),
        }

        scored: Dict[str, Any] = {}
        for label, params in variants.items():
            result = self.scorer.score(params)
            replay = self.scorer.score_replay(params)
            scored[label] = {
                "params": asdict(params),
                "score": result.to_dict(),
                "replay": replay.to_dict(),
            }

        experiment_matrix = self._build_experiment_matrix(base)

        eth = scored["eth_only"]["score"]
        btc = scored["btc_only"]["score"]
        eth_btc = scored["eth_btc"]["score"]
        eth_swarm = scored["eth_swarm_only"]["score"]
        best_research_candidate = experiment_matrix["best_candidate"]
        best_low_sample_candidate = experiment_matrix.get("best_low_sample_candidate") or {}

        summary = {
            "verdict_basis": "active_data_dir",
            "best_variant_by_score": self._select_best_variant(scored, require_accepted=True) or "no_replay_accepted_variant",
            "best_exploratory_variant_by_score": self._select_best_variant(scored) or "no_variant_with_filtered_trades",
            "supported_symbols": self._supported_symbols(eth, btc),
            "eth_vs_btc_pnl_delta": round(float(eth.get("total_pnl", 0.0)) - float(btc.get("total_pnl", 0.0)), 2),
            "eth_btc_expansion_penalty": round(float(eth_btc.get("total_pnl", 0.0)) - float(eth.get("total_pnl", 0.0)), 2),
            "eth_swarm_edge_positive": float(eth_swarm.get("total_pnl", 0.0)) > 0.0,
            "replay_acceptance_any": any(item["replay"].get("accepted") for item in scored.values()),
            "best_research_candidate": best_research_candidate,
            "best_low_sample_candidate": best_low_sample_candidate,
        }

        return {
            "summary": summary,
            "variants": scored,
            "experiment_matrix": experiment_matrix,
            "archive_context": self._build_archive_context(base),
        }

    def scan_live_inventory(self, existing_report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self.skip_inventory:
            previous_inventory = {}
            if isinstance(existing_report, dict):
                previous_inventory = existing_report.get("inventory_snapshot", {}) or {}
            if isinstance(previous_inventory, dict) and previous_inventory.get("strict") and previous_inventory.get("broad"):
                carried = json.loads(json.dumps(previous_inventory))
                carried["refresh_mode"] = "carried_forward"
                carried["source_generated_at"] = str(existing_report.get("generated_at", "") or "")
                strict = carried.get("strict", {})
                broad = carried.get("broad", {})
                if isinstance(strict, dict):
                    strict_telemetry = dict(strict.get("telemetry", {}) or {})
                    strict_telemetry["skipped"] = True
                    strict_telemetry["carried_forward"] = True
                    strict["telemetry"] = strict_telemetry
                if isinstance(broad, dict):
                    broad_telemetry = dict(broad.get("telemetry", {}) or {})
                    broad_telemetry["skipped"] = True
                    broad_telemetry["carried_forward"] = True
                    broad["telemetry"] = broad_telemetry
                return carried
            return {
                "refresh_mode": "skipped_no_prior_snapshot",
                "source_generated_at": "",
                "strict": {
                    "config": self._inventory_config_summary(self.config),
                    "telemetry": {"skipped": True},
                    **self._summarize_markets([]),
                },
                "broad": {
                    "config": self._inventory_config_summary(self.config),
                    "telemetry": {"skipped": True},
                    **self._summarize_markets([]),
                },
            }

        strict_config = get_polymarket_cli_config(
            execution_mode=ExecutionMode.DRY_RUN,
            _data_dir_override=self.config.data_dir,
            search_symbols=list(self.config.search_symbols),
            max_markets_to_analyze=max(25, int(self.config.max_markets_to_analyze)),
            min_liquidity_usd=float(self.config.min_liquidity_usd),
            min_volume_24h_usd=float(self.config.min_volume_24h_usd),
            max_expiry_hours=self.config.max_expiry_hours,
            min_expiry_hours=self.config.min_expiry_hours,
        )
        broad_symbols = sorted({*(self.config.search_symbols or ["ETH"]), "BTC", "ETH"})
        broad_config = get_polymarket_cli_config(
            execution_mode=ExecutionMode.DRY_RUN,
            _data_dir_override=self.config.data_dir,
            search_symbols=broad_symbols,
            max_markets_to_analyze=max(100, int(self.config.max_markets_to_analyze)),
            min_liquidity_usd=min(float(self.config.min_liquidity_usd), 1000.0),
            min_volume_24h_usd=0.0,
            max_expiry_hours=None,
            min_expiry_hours=None,
        )

        strict_scanner = self.scanner_factory(strict_config)
        strict_markets = self._scan_markets_with_timeout(
            strict_scanner,
            timeout_seconds=self.strict_inventory_timeout_seconds,
        )

        broad_scanner = self.scanner_factory(broad_config)
        if hasattr(strict_scanner, "cli") and hasattr(broad_scanner, "cli"):
            broad_scanner.cli = strict_scanner.cli
        broad_markets = self._scan_markets_with_timeout(
            broad_scanner,
            timeout_seconds=self.broad_inventory_timeout_seconds,
        )

        return {
            "refresh_mode": "live_scan",
            "source_generated_at": "",
            "strict": {
                "config": self._inventory_config_summary(strict_config),
                "telemetry": strict_scanner.last_scan_telemetry,
                **self._summarize_markets(strict_markets),
            },
            "broad": {
                "config": self._inventory_config_summary(broad_config),
                "telemetry": broad_scanner.last_scan_telemetry,
                **self._summarize_markets(broad_markets),
            },
        }

    def build_priorities(
        self,
        edge_snapshot: Dict[str, Any],
        performance_summary: Dict[str, Any],
        swarm_health: Dict[str, Any],
        runtime_swarm_health: Dict[str, Any],
        inventory_snapshot: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        priorities: List[ResearchPriority] = []
        variants = edge_snapshot.get("variants", {})
        summary = edge_snapshot.get("summary", {})
        experiment_matrix = edge_snapshot.get("experiment_matrix", {})
        strict = inventory_snapshot.get("strict", {})
        broad = inventory_snapshot.get("broad", {})
        strict_telemetry = strict.get("telemetry", {})
        perf_by_source = performance_summary.get("by_source", {})
        perf_by_timeframe = performance_summary.get("by_timeframe", {})
        confidence_diagnostics = performance_summary.get("confidence_diagnostics", {}) if isinstance(performance_summary, dict) else {}
        direction_diagnostics = performance_summary.get("direction_diagnostics", {}) if isinstance(performance_summary, dict) else {}
        entry_price_diagnostics = performance_summary.get("entry_price_diagnostics", {}) if isinstance(performance_summary, dict) else {}
        replay = performance_summary.get("replay", {})
        holdout_probe = replay.get("trailing_holdout_probe", {}) if isinstance(replay, dict) else {}
        best_candidate = experiment_matrix.get("best_candidate") or {}
        low_sample_candidate = experiment_matrix.get("best_low_sample_candidate") or {}
        best_low_sample_concentration = self._normalize_patch_concentration_row(
            entry_price_diagnostics.get("best_low_sample_concentration", {})
        )
        best_low_sample_independence = self._build_patch_independence_verdict(best_low_sample_concentration)
        swarm_ready = bool(swarm_health.get("ready", False))
        unavailable_models = int(swarm_health.get("unavailable_models", 0))
        runtime_ready = bool(runtime_swarm_health.get("ready", False))
        runtime_recent = bool(runtime_swarm_health.get("latest_data_dir"))
        runtime_error_codes = runtime_swarm_health.get("error_code_counts", {}) or {}
        recent_runtime_error_codes = runtime_swarm_health.get("recent_run_error_code_counts", {}) or {}
        persistently_healthy_providers = runtime_swarm_health.get("persistently_healthy_providers", []) or []
        persistently_blocked_providers = runtime_swarm_health.get("persistently_blocked_providers", []) or []
        most_common_recent_healthy_provider_set = runtime_swarm_health.get("most_common_recent_healthy_provider_set", "") or "none"
        single_provider_only_runs = int(runtime_swarm_health.get("single_provider_only_runs", 0) or 0)
        single_provider_only_rate = float(runtime_swarm_health.get("single_provider_only_rate", 0.0) or 0.0)
        latest_runtime_fresh = bool(runtime_swarm_health.get("fresh_enough_for_runtime_summary", False))
        latest_runtime_scan_summary = runtime_swarm_health.get("latest_runtime_scan_summary", {}) or {}
        historical_runs_considered = int(runtime_swarm_health.get("historical_runs_considered", 0) or 0)
        historical_ready_runs = int(runtime_swarm_health.get("historical_ready_runs", 0) or 0)
        historical_runtime_error_codes = runtime_swarm_health.get("historical_run_error_code_counts", {}) or {}
        historical_provider_ok_rates = runtime_swarm_health.get("historical_provider_ok_rates", {}) or {}
        historical_healthy_provider_sets = runtime_swarm_health.get("historical_healthy_provider_sets", {}) or {}
        historical_xai_only_runs = int(runtime_swarm_health.get("historical_xai_only_runs", 0) or 0)
        historical_zero_healthy_provider_runs = int(runtime_swarm_health.get("historical_zero_healthy_provider_runs", 0) or 0)
        historical_other_provider_mix_runs = int(runtime_swarm_health.get("historical_other_provider_mix_runs", 0) or 0)
        historical_xai_only_rate = float(runtime_swarm_health.get("historical_xai_only_rate", 0.0) or 0.0)
        historical_zero_healthy_provider_rate = float(runtime_swarm_health.get("historical_zero_healthy_provider_rate", 0.0) or 0.0)
        most_common_historical_healthy_provider_set = (
            runtime_swarm_health.get("most_common_historical_healthy_provider_set", "") or "none"
        )

        if summary.get("supported_symbols") == ["ETH"]:
            priorities.append(
                ResearchPriority(
                    code="eth_first_until_btc_proves_itself",
                    title="Keep the strategy ETH-first until BTC earns a positive replay edge",
                    rationale=(
                        "ETH remains the only currently supported symbol lane while BTC replay is weaker or negative."
                    ),
                    actions=[
                        "Keep default symbol focus on ETH for attended trading.",
                        "Treat BTC as research-only until its replay score and holdout both improve.",
                    ],
                )
            )

        if best_candidate and not best_candidate.get("replay_accepted", False) and float(best_candidate.get("total_pnl", 0.0)) > 0.0:
            priorities.append(
                ResearchPriority(
                    code="paper_test_best_measured_variant",
                    title="Paper-test the strongest measured ETH variant before any config change",
                    rationale=(
                        "A better in-sample ETH configuration exists, but it still has no passing holdout and must stay in research until validated."
                    ),
                    actions=[
                        (
                            f"Use `{best_candidate.get('label', 'candidate')}` as the next paper-soak candidate "
                            f"with score {float(best_candidate.get('score', 0.0)):.2f} and "
                            f"PnL ${float(best_candidate.get('total_pnl', 0.0)):+.2f}."
                        ),
                        "Keep the production default unchanged until that candidate earns resolved out-of-sample support.",
                    ],
                )
            )
        elif (
            not best_candidate
            and low_sample_candidate
            and float(low_sample_candidate.get("total_pnl", 0.0)) > 0.0
        ):
            priorities.append(
                ResearchPriority(
                    code="increase_sample_before_promoting_candidate",
                    title="Increase sample size before promoting any exploratory ETH variant",
                    rationale=(
                        "The best positive exploratory lane is based on too few trades to treat as meaningful evidence."
                    ),
                    actions=[
                        (
                            f"Treat `{low_sample_candidate.get('label', 'candidate')}` as a low-sample lead only; "
                            f"it has {int(low_sample_candidate.get('filtered_trades', 0))} trades, below the "
                            f"{MIN_RESEARCH_CANDIDATE_TRADES} trade research bar."
                        ),
                        "Gather more resolved ETH paper trades before changing defaults or celebrating a candidate edge.",
                    ],
                )
            )

        if not swarm_ready and unavailable_models > 0:
            priorities.append(
                ResearchPriority(
                    code="restore_swarm_providers",
                    title="Restore swarm provider availability before trusting paper soaks",
                    rationale=(
                        "Recent candidate runs are abstaining because the configured swarm providers are unavailable at runtime."
                    ),
                    actions=[
                        f"Fix the {unavailable_models} unavailable configured swarm models before interpreting no-trade paper runs as strategy evidence.",
                        "Treat recent swarm abstains as infrastructure failures unless the prediction artifacts show real model outputs.",
                    ],
                )
            )

        if runtime_recent and not runtime_ready:
            recent_runs_considered = int(runtime_swarm_health.get("recent_runs_considered", 0) or 0)
            recent_ready_runs = int(runtime_swarm_health.get("recent_ready_runs", 0) or 0)
            priorities.append(
                ResearchPriority(
                    code="fix_runtime_swarm_health",
                    title="Fix runtime swarm provider failures before interpreting paper abstains",
                    rationale=(
                        "Recent paper artifacts show the swarm cannot currently reach the required model count at runtime, "
                        "so no-trade cycles are partly infrastructure-driven."
                    ),
                    actions=[
                        (
                            f"Address recent runtime provider failures in `{runtime_swarm_health.get('latest_data_dir', '')}` "
                            f"before treating abstains as alpha evidence."
                        ),
                        (
                            f"Recent runtime error codes: {runtime_error_codes or {'unknown': 0}}. "
                            "Funding or auth fixes should come before new strategy tuning."
                        ),
                        (
                            f"Recent run-level error pattern: {recent_runtime_error_codes or {'unknown': 0}}."
                            if recent_runtime_error_codes
                            else "Recent run-level error pattern is not available yet."
                        ),
                        (
                            f"Persistently healthy providers: {persistently_healthy_providers or ['none']}; "
                            f"persistently blocked providers: {persistently_blocked_providers or ['none']}."
                        ),
                        (
                            f"Most common recent healthy-provider set: {most_common_recent_healthy_provider_set}; "
                            f"single-provider-only runs: {single_provider_only_runs} ({single_provider_only_rate:.1%})."
                        ),
                        (
                            f"Recent runtime cohort: {recent_ready_runs}/{recent_runs_considered} runs were runtime-ready."
                            if recent_runs_considered > 0
                            else "Recent runtime cohort is not available yet."
                        ),
                        (
                            f"Historical runtime cohort: {historical_ready_runs}/{historical_runs_considered} runs were runtime-ready."
                            if historical_runs_considered > 0
                            else "Historical runtime cohort is not available yet."
                        ),
                        (
                            f"Historical provider ok-rates: {historical_provider_ok_rates or {'unknown': 0.0}}."
                            if historical_provider_ok_rates
                            else "Historical provider ok-rates are not available yet."
                        ),
                        (
                            f"Historical healthy-provider sets: {historical_healthy_provider_sets or {'none': 0}}; "
                            f"most common historical healthy-provider set: {most_common_historical_healthy_provider_set}."
                            if historical_healthy_provider_sets
                            else "Historical healthy-provider-set mix is not available yet."
                        ),
                        (
                            f"Historical failure composition: xai-only={historical_xai_only_runs} ({historical_xai_only_rate:.1%}), "
                            f"no-healthy-provider={historical_zero_healthy_provider_runs} ({historical_zero_healthy_provider_rate:.1%}), "
                            f"other={historical_other_provider_mix_runs}."
                        ),
                        (
                            f"Historical run-level error pattern: {historical_runtime_error_codes or {'unknown': 0}}."
                            if historical_runtime_error_codes
                            else "Historical run-level error pattern is not available yet."
                        ),
                    ],
                )
            )

        if strict.get("tradeable_markets", 0) == 0 and broad.get("tradeable_markets", 0) > 0:
            low_volume_hits = strict_telemetry.get("exclusion_reasons", {}).get("low_volume_24h", 0)
            priorities.append(
                ResearchPriority(
                    code="split_inventory_policy",
                    title="Split inventory policy between short-horizon ETH and broader ladder markets",
                    rationale=(
                        "Strict production filters are finding no tradeable markets even though the broader live surface still has inventory."
                    ),
                    actions=[
                        f"Rework the 24h volume gate, which is currently blocking {low_volume_hits} candidates in the latest strict scan.",
                        "Separate binary up/down duration logic from longer-dated ladder and range markets before changing ranking logic.",
                    ],
                )
            )
        if (
            latest_runtime_fresh
            and str(latest_runtime_scan_summary.get("status", "") or "") == "NO_TRADEABLE_MARKETS_IN_LATEST_RUNTIME_SCAN"
        ):
            priorities.append(
                ResearchPriority(
                    code="fix_latest_runtime_inventory_block",
                    title="Fix the latest ETH runtime inventory blockage before reading more no-trade cycles as strategy evidence",
                    rationale=(
                        "The freshest ETH runtime cycle found zero tradeable markets, so the immediate blocker is current inventory quality rather than model output quality."
                    ),
                    actions=[
                        (
                            f"Latest runtime scan counts were "
                            f"{int(latest_runtime_scan_summary.get('query_count', 0) or 0)} queries / "
                            f"{int(latest_runtime_scan_summary.get('raw_records', 0) or 0)} raw / "
                            f"{int(latest_runtime_scan_summary.get('parsed', 0) or 0)} parsed / "
                            f"{int(latest_runtime_scan_summary.get('filtered', 0) or 0)} filtered / "
                            f"{int(latest_runtime_scan_summary.get('tradeable', 0) or 0)} tradeable."
                        ),
                        f"Top latest-runtime exclusions were: {self._format_runtime_scan_exclusions(latest_runtime_scan_summary)}.",
                        "Treat the newest no-trade cycle as inventory-blocked first; only secondarily as a swarm-health signal.",
                    ],
                )
            )

        arb_stats = perf_by_source.get("arbitrage") or {}
        if float(arb_stats.get("pnl", 0.0)) < 0.0:
            priorities.append(
                ResearchPriority(
                    code="keep_arb_structural_only",
                    title="Keep arbitrage structural and strict",
                    rationale=(
                        "Recent performance still shows arbitrage losing money, so broad discrepancy hunting is dilutive."
                    ),
                    actions=[
                        "Limit arb research to ladder, range, and complementary coherence setups.",
                        "Require replay evidence before broadening any arbitrage filter.",
                    ],
                )
            )

        if str(confidence_diagnostics.get("verdict", "") or "") == "HIGH_CONFIDENCE_ANTI_SIGNAL":
            high_confidence = confidence_diagnostics.get("high_confidence", {}) if isinstance(confidence_diagnostics, dict) else {}
            low_confidence = confidence_diagnostics.get("low_confidence", {}) if isinstance(confidence_diagnostics, dict) else {}
            threshold = float(confidence_diagnostics.get("high_confidence_threshold", 0.5) or 0.5)
            priorities.append(
                ResearchPriority(
                    code="repair_confidence_calibration",
                    title="Repair confidence calibration before trusting stronger signals",
                    rationale=(
                        "The current higher-confidence cohort is performing worse than the lower-confidence cohort, "
                        "so increasing conviction does not currently improve edge quality."
                    ),
                    actions=[
                        (
                            f"Treat >= {threshold:.0%} confidence as untrusted until calibration improves; the current cohort is "
                            f"{int(high_confidence.get('count', 0) or 0)} trades with "
                            f"{float(high_confidence.get('win_rate', 0.0) or 0.0):.1%} win rate and "
                            f"${float(high_confidence.get('total_pnl', 0.0) or 0.0):+.2f} PnL."
                        ),
                        (
                            f"Compare against the lower-confidence cohort ({int(low_confidence.get('count', 0) or 0)} trades, "
                            f"{float(low_confidence.get('win_rate', 0.0) or 0.0):.1%} win rate) before promoting any new threshold."
                        ),
                        "Bias future swarm work toward calibration, abstain rules, and price anchoring rather than stronger conviction prompts.",
                    ],
                )
            )
            gate_verdict = confidence_diagnostics.get("gate_verdict", {}) if isinstance(confidence_diagnostics, dict) else {}
            best_cap = confidence_diagnostics.get("best_cap", {}) if isinstance(confidence_diagnostics, dict) else {}
            if str(gate_verdict.get("status", "") or "") == "NO_PROMOTABLE_CONFIDENCE_GATE":
                priorities.append(
                    ResearchPriority(
                        code="do_not_expect_confidence_gating_fix",
                        title="Do not expect a simple confidence gate to rescue the current strategy",
                        rationale=(
                            "The best simple confidence cap in the current journal is still negative, "
                            "so thresholding conviction alone is not enough to create edge."
                        ),
                        actions=[
                            (
                                f"The best current confidence cap is <= {float(best_cap.get('threshold', 0.0) or 0.0):.0%} with "
                                f"{int(best_cap.get('count', 0) or 0)} trades and "
                                f"${float(best_cap.get('total_pnl', 0.0) or 0.0):+.2f} PnL."
                            ),
                            "Prioritize better probability calibration and market selection instead of only clipping high-confidence trades.",
                        ],
                    )
                )

        if str(direction_diagnostics.get("verdict", "") or "") == "YES_DIRECTION_ANTI_SIGNAL":
            best_direction = direction_diagnostics.get("best_direction", {}) if isinstance(direction_diagnostics, dict) else {}
            yes_stats = (direction_diagnostics.get("by_direction", {}) or {}).get("YES", {})
            worst_pocket = direction_diagnostics.get("worst_direction_timeframe", {}) if isinstance(direction_diagnostics, dict) else {}
            priorities.append(
                ResearchPriority(
                    code="strip_yes_side_bias",
                    title="Strip YES-side bias out of the current swarm before trusting directional calls",
                    rationale=(
                        "The current healthy journal shows YES calls are materially worse than NO calls, so the model is not just miscalibrated, it is leaning into the wrong side."
                    ),
                    actions=[
                        (
                            f"Treat current YES-side calls as anti-signal until fixed: {int(yes_stats.get('count', 0) or 0)} trades, "
                            f"{float(yes_stats.get('win_rate', 0.0) or 0.0):.1%} win rate, "
                            f"${float(yes_stats.get('total_pnl', 0.0) or 0.0):+.2f} PnL."
                        ),
                        (
                            f"The least-bad current side is {str(best_direction.get('direction', 'none') or 'none')}, "
                            f"but it is still not promotable."
                        ),
                        (
                            f"The dominant current directional drag is "
                            f"{self._format_best_direction_timeframe(worst_pocket)}."
                            if worst_pocket
                            else "Directional drag concentration is not available yet."
                        ),
                        "Bias future swarm prompt work toward directional neutrality and stronger downside / contrarian checks rather than stronger YES conviction.",
                    ],
                )
            )
            pocket_verdict = direction_diagnostics.get("pocket_verdict", {}) if isinstance(direction_diagnostics, dict) else {}
            best_pocket = direction_diagnostics.get("best_direction_timeframe", {}) if isinstance(direction_diagnostics, dict) else {}
            if str(pocket_verdict.get("status", "") or "") == "NO_PROMOTABLE_DIRECTION_TIMEFRAME_POCKET":
                priorities.append(
                    ResearchPriority(
                        code="do_not_promote_direction_timeframe_patch",
                        title="Do not promote the best direction-timeframe patch without more sample",
                        rationale=(
                            "The least-bad direction-timeframe pocket is still too thin to treat as a real edge."
                        ),
                        actions=[
                            (
                                f"Current best pocket is {str(best_pocket.get('direction', 'none') or 'none')} / "
                                f"{str(best_pocket.get('timeframe', 'unknown') or 'unknown')} with "
                                f"{int(best_pocket.get('count', 0) or 0)} trades and "
                                f"${float(best_pocket.get('total_pnl', 0.0) or 0.0):+.2f} PnL."
                            ),
                            "Keep this as a research patch only until it clears the normal minimum trade bar with positive PnL.",
                        ],
                    )
                )
            exclusion_rescue = direction_diagnostics.get("exclusion_rescue", {}) if isinstance(direction_diagnostics, dict) else {}
            if str(exclusion_rescue.get("status", "") or "") == "NO_SIMPLE_EXCLUSION_RESCUE":
                scenarios = exclusion_rescue.get("scenarios", []) or []
                best_residual_row = max(
                    (row for row in scenarios if isinstance(row, dict)),
                    key=lambda row: float(row.get("residual_pnl", float("-inf")) or float("-inf")),
                    default={},
                )
                priorities.append(
                    ResearchPriority(
                        code="do_not_expect_one_filter_fix",
                        title="Do not expect one exclusion filter to rescue the current book",
                        rationale=(
                            "Even after dropping the worst measured pockets, the remaining healthy cohort is still negative, so the edge problem is broader than one bad slice."
                        ),
                        actions=[
                            (
                                f"Best simple exclusion rescue still leaves residual PnL at "
                                f"${float(best_residual_row.get('residual_pnl', 0.0) or 0.0):+.2f} "
                                f"after `{str(best_residual_row.get('label', 'unknown') or 'unknown')}`."
                            ),
                            "Treat the current failure as a stacked weakness pattern, not a single filter bug.",
                        ],
                    )
                )

        positive_timeframes = []
        for timeframe, stats in (perf_by_timeframe or {}).items():
            if not isinstance(stats, dict):
                continue
            pnl = float(stats.get("pnl", 0.0) or 0.0)
            count = int(stats.get("count", 0) or 0)
            if pnl > 0.0:
                positive_timeframes.append(
                    {
                        "timeframe": str(timeframe),
                        "pnl": pnl,
                        "count": count,
                    }
                )
        if len(positive_timeframes) == 1 and int(positive_timeframes[0]["count"]) < MIN_RESEARCH_CANDIDATE_TRADES:
            only_positive = positive_timeframes[0]
            priorities.append(
                ResearchPriority(
                    code="do_not_generalize_ultra_short_blip",
                    title="Do not generalize the lone positive timeframe without more samples",
                    rationale=(
                        "The only positive realized lane is concentrated in a tiny sample, so it is not enough to claim a durable edge."
                    ),
                    actions=[
                        (
                            f"Treat `{only_positive['timeframe']}` as exploratory only: "
                            f"${float(only_positive['pnl']):+.2f} across {int(only_positive['count'])} trades."
                        ),
                        "Require at least the normal research trade-count bar before promoting any timeframe-specific edge thesis.",
                    ],
                )
            )

        if str(best_low_sample_independence.get("status", "") or "") == "NON_INDEPENDENT_PATCH":
            priorities.append(
                ResearchPriority(
                    code="do_not_promote_non_independent_tail_patch",
                    title="Do not promote the surviving cheap-tail ETH patch as a real edge",
                    rationale=(
                        "The only positive entry-price patch is not independent enough to trust, because it is still carried by too few trades and fails without its largest winner."
                    ),
                    actions=[
                        (
                            f"Current patch concentration is {int(best_low_sample_concentration.get('count', 0) or 0)} trades across "
                            f"{int(best_low_sample_concentration.get('unique_markets', 0) or 0)} markets, with residual ex-best "
                            f"${float(best_low_sample_concentration.get('residual_pnl_without_largest_win', 0.0) or 0.0):+.2f}."
                        ),
                        (
                            f"Treat reason codes {list(best_low_sample_independence.get('reason_codes', []) or [])} as a hard stop on promoting this patch."
                        ),
                        "Require a positive ETH patch that survives without its top win and spans more distinct markets before treating it as real alpha.",
                    ],
                )
            )

        if not replay.get("accepted", False) or not summary.get("replay_acceptance_any", False):
            holdout_score = replay.get("holdout", {}).get("score", 0.0)
            probe_has_support = bool(holdout_probe.get("any_filtered_holdout", False))
            probe_best_filtered = int(holdout_probe.get("best_filtered_holdout_trades", 0) or 0)
            priorities.append(
                ResearchPriority(
                    code="holdout_first",
                    title="Use holdout acceptance as the non-negotiable shipping gate",
                    rationale=(
                        "The current strategy still lacks a clean accepted holdout result, so in-sample wins are not enough."
                    ),
                    actions=[
                        f"Do not treat current optimization wins as production-ready while holdout score remains {holdout_score:.2f}.",
                        "Favor experiments that increase filtered holdout trade count before chasing marginal score gains.",
                        (
                            "The diagnostic widened trailing-holdout probe still finds no filtered holdout support across 20%-50% late-cohort splits."
                            if holdout_probe and not probe_has_support
                            else (
                                f"The diagnostic widened trailing-holdout probe tops out at {probe_best_filtered} filtered holdout trades; that is still not enough to ship."
                                if holdout_probe
                                else "Keep using explicit replay diagnostics before trusting in-sample wins."
                            )
                        ),
                    ],
                )
            )

        if not priorities:
            priorities.append(
                ResearchPriority(
                    code="continue_measurement",
                    title="Continue the research loop",
                    rationale="The system is stable enough to keep gathering evidence, but the edge still needs more resolved trades.",
                    actions=[
                        "Run another paper soak.",
                        "Refresh the edge report after new trades resolve.",
                    ],
                )
            )

        return [asdict(priority) for priority in priorities]

    def build_blockers(
        self,
        edge_snapshot: Dict[str, Any],
        performance_summary: Dict[str, Any],
        runtime_swarm_health: Dict[str, Any],
        inventory_snapshot: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        blockers: List[ResearchBlocker] = []
        replay = performance_summary.get("replay", {}) if isinstance(performance_summary, dict) else {}
        holdout_probe = replay.get("trailing_holdout_probe", {}) if isinstance(replay, dict) else {}
        confidence_diagnostics = performance_summary.get("confidence_diagnostics", {}) if isinstance(performance_summary, dict) else {}
        direction_diagnostics = performance_summary.get("direction_diagnostics", {}) if isinstance(performance_summary, dict) else {}
        entry_price_diagnostics = performance_summary.get("entry_price_diagnostics", {}) if isinstance(performance_summary, dict) else {}
        low_sample_candidate = edge_snapshot.get("summary", {}).get("best_low_sample_candidate") or {}
        best_low_sample_concentration = self._normalize_patch_concentration_row(
            entry_price_diagnostics.get("best_low_sample_concentration", {})
        )
        best_low_sample_independence = self._build_patch_independence_verdict(best_low_sample_concentration)
        recent_runs_considered = int(runtime_swarm_health.get("recent_runs_considered", 0) or 0)
        recent_ready_runs = int(runtime_swarm_health.get("recent_ready_runs", 0) or 0)
        single_provider_only_runs = int(runtime_swarm_health.get("single_provider_only_runs", 0) or 0)
        single_provider_only_rate = float(runtime_swarm_health.get("single_provider_only_rate", 0.0) or 0.0)
        latest_runtime_fresh = bool(runtime_swarm_health.get("fresh_enough_for_runtime_summary", False))
        latest_runtime_scan_summary = runtime_swarm_health.get("latest_runtime_scan_summary", {}) or {}
        historical_runs_considered = int(runtime_swarm_health.get("historical_runs_considered", 0) or 0)
        historical_ready_runs = int(runtime_swarm_health.get("historical_ready_runs", 0) or 0)
        historical_healthy_provider_sets = runtime_swarm_health.get("historical_healthy_provider_sets", {}) or {}
        historical_xai_only_rate = float(runtime_swarm_health.get("historical_xai_only_rate", 0.0) or 0.0)
        historical_zero_healthy_provider_rate = float(runtime_swarm_health.get("historical_zero_healthy_provider_rate", 0.0) or 0.0)
        inventory_refresh_mode = str(inventory_snapshot.get("refresh_mode", "live_scan") or "live_scan")
        strict_tradeable = int(inventory_snapshot.get("strict", {}).get("tradeable_markets", 0) or 0)
        broad_tradeable = int(inventory_snapshot.get("broad", {}).get("tradeable_markets", 0) or 0)

        if recent_runs_considered > 0 and recent_ready_runs <= 0:
            evidence = f"{recent_ready_runs}/{recent_runs_considered} recent runtime runs were consensus-ready."
            if historical_runs_considered > 0:
                evidence += f" Historical cohort: {historical_ready_runs}/{historical_runs_considered}."
            implication = (
                "Recent paper abstains are infrastructure-driven, so they cannot be treated as real no-edge evidence."
            )
            if historical_runs_considered >= 5 and historical_ready_runs <= 0:
                implication += " The runtime lane looks chronically unavailable, not just temporarily degraded."
            blockers.append(
                ResearchBlocker(
                    code="runtime_swarm_unavailable",
                    title="Runtime swarm is not operational",
                    evidence=evidence,
                    implication=implication,
                )
            )

        if (
            latest_runtime_fresh
            and str(latest_runtime_scan_summary.get("status", "") or "") == "NO_TRADEABLE_MARKETS_IN_LATEST_RUNTIME_SCAN"
        ):
            blockers.append(
                ResearchBlocker(
                    code="latest_runtime_inventory_blocked",
                    title="The latest ETH runtime cycle found no tradeable markets",
                    evidence=(
                        f"Latest runtime scan counts were "
                        f"{int(latest_runtime_scan_summary.get('query_count', 0) or 0)} queries / "
                        f"{int(latest_runtime_scan_summary.get('raw_records', 0) or 0)} raw / "
                        f"{int(latest_runtime_scan_summary.get('parsed', 0) or 0)} parsed / "
                        f"{int(latest_runtime_scan_summary.get('filtered', 0) or 0)} filtered / "
                        f"{int(latest_runtime_scan_summary.get('tradeable', 0) or 0)} tradeable. "
                        f"Top exclusions: {self._format_runtime_scan_exclusions(latest_runtime_scan_summary)}."
                    ),
                    implication=(
                        "The freshest ETH runtime bottleneck is current inventory scarcity, so the latest no-trade cycle should be read as search-and-filter blockage before provider consensus or alpha quality."
                    ),
                )
            )

        if recent_runs_considered > 0 and single_provider_only_rate >= 0.8:
            evidence = (
                f"{single_provider_only_runs}/{recent_runs_considered} recent runs used a single healthy provider set "
                f"({runtime_swarm_health.get('most_common_recent_healthy_provider_set', 'none')})."
            )
            historical_xai_only = int(historical_healthy_provider_sets.get("xai", 0) or 0)
            historical_none = int(historical_healthy_provider_sets.get("none", 0) or 0)
            if historical_runs_considered > 0 and (historical_xai_only > 0 or historical_none > 0):
                evidence += (
                    f" Historical healthy-provider sets are xai={historical_xai_only}, none={historical_none}."
                )
                evidence += (
                    f" Historical failure rates are xai-only={historical_xai_only_rate:.1%}, "
                    f"no-healthy-provider={historical_zero_healthy_provider_rate:.1%}."
                )
            blockers.append(
                ResearchBlocker(
                    code="single_provider_control",
                    title="Recent ETH runs are collapsing to single-provider control",
                    evidence=evidence,
                    implication=(
                        "Current ETH runtime behavior is not a true swarm, so calibration and abstain behavior are not representative."
                    ),
                )
            )

        if not bool(replay.get("accepted", False)) and not bool(holdout_probe.get("any_filtered_holdout", False)):
            blockers.append(
                ResearchBlocker(
                    code="no_holdout_support",
                    title="There is no filtered holdout support for the current ETH configuration",
                    evidence=(
                        f"Replay accepted={replay.get('accepted', False)} and widened holdout support="
                        f"{holdout_probe.get('any_filtered_holdout', False)}."
                    ),
                    implication=(
                        "There is no out-of-sample evidence to justify deployment or BTC expansion."
                    ),
                )
            )

        if low_sample_candidate and int(low_sample_candidate.get("filtered_trades", 0) or 0) < MIN_RESEARCH_CANDIDATE_TRADES:
            blockers.append(
                ResearchBlocker(
                    code="positive_lane_low_sample",
                    title="The only positive exploratory lane is still low sample",
                    evidence=(
                        f"{low_sample_candidate.get('label', 'candidate')} has "
                        f"{int(low_sample_candidate.get('filtered_trades', 0) or 0)} trades."
                    ),
                    implication=(
                        "The observed positive patch is too small to promote into a deployable ETH edge thesis."
                    ),
                )
            )

        if str(best_low_sample_independence.get("status", "") or "") == "NON_INDEPENDENT_PATCH":
            blockers.append(
                ResearchBlocker(
                    code="positive_patch_non_independent",
                    title="The only positive ETH patch is non-independent",
                    evidence=(
                        f"Best low-sample patch is {int(best_low_sample_concentration.get('count', 0) or 0)} trades across "
                        f"{int(best_low_sample_concentration.get('unique_markets', 0) or 0)} markets, with residual ex-best "
                        f"${float(best_low_sample_concentration.get('residual_pnl_without_largest_win', 0.0) or 0.0):+.2f}."
                    ),
                    implication=(
                        "The surviving positive patch still looks like a one-off tail winner rather than a repeatable ETH edge."
                    ),
                )
            )

        total_pnl = float(performance_summary.get("total_pnl", 0.0) or 0.0)
        profit_factor_raw = performance_summary.get("profit_factor", 0.0)
        try:
            profit_factor = float(profit_factor_raw)
        except (TypeError, ValueError):
            profit_factor = 0.0
        if total_pnl < 0.0:
            blockers.append(
                ResearchBlocker(
                    code="negative_realized_book",
                    title="The realized ETH book is still negative",
                    evidence=(
                        f"Closed-trade PnL is ${total_pnl:+.2f} with profit factor {profit_factor_raw}."
                    ),
                    implication=(
                        "The current realized book does not support live deployment, even before accounting for runtime degradation."
                    ),
                )
            )

        if str(confidence_diagnostics.get("verdict", "") or "") == "HIGH_CONFIDENCE_ANTI_SIGNAL":
            high_confidence = confidence_diagnostics.get("high_confidence", {}) if isinstance(confidence_diagnostics, dict) else {}
            threshold = float(confidence_diagnostics.get("high_confidence_threshold", 0.5) or 0.5)
            blockers.append(
                ResearchBlocker(
                    code="high_confidence_anti_signal",
                    title="Higher-confidence predictions are behaving like anti-signal",
                    evidence=(
                        f">= {threshold:.0%} confidence cohort: {int(high_confidence.get('count', 0) or 0)} trades, "
                        f"{float(high_confidence.get('win_rate', 0.0) or 0.0):.1%} win rate, "
                        f"${float(high_confidence.get('total_pnl', 0.0) or 0.0):+.2f} PnL."
                    ),
                    implication=(
                        "The current confidence scale is not trustworthy enough for deployment, because stronger conviction is not translating into better outcomes."
                    ),
                )
            )

        if str(direction_diagnostics.get("verdict", "") or "") == "YES_DIRECTION_ANTI_SIGNAL":
            yes_stats = (direction_diagnostics.get("by_direction", {}) or {}).get("YES", {})
            blockers.append(
                ResearchBlocker(
                    code="yes_direction_anti_signal",
                    title="YES-side directional calls are behaving like anti-signal",
                    evidence=(
                        f"YES cohort: {int(yes_stats.get('count', 0) or 0)} trades, "
                        f"{float(yes_stats.get('win_rate', 0.0) or 0.0):.1%} win rate, "
                        f"${float(yes_stats.get('total_pnl', 0.0) or 0.0):+.2f} PnL."
                    ),
                    implication=(
                        "The current swarm is not only miscalibrated on confidence; it is also leaning into a losing direction, so directional calls are not trustworthy enough for deployment."
                    ),
                )
            )

        if inventory_refresh_mode in {"live_scan", "carried_forward"} and strict_tradeable <= 0 and broad_tradeable > 0:
            blockers.append(
                ResearchBlocker(
                    code="strict_inventory_empty",
                    title="Production-style inventory is empty while broader inventory still exists",
                    evidence=(
                        f"Strict tradeable markets={strict_tradeable}, broad tradeable markets={broad_tradeable}."
                    ),
                    implication=(
                        "The search universe and filters still need work before the bot can reliably source candidates."
                    ),
                )
            )

        return [asdict(blocker) for blocker in blockers]

    def build_deployment_verdict(
        self,
        edge_snapshot: Dict[str, Any],
        performance_summary: Dict[str, Any],
        runtime_swarm_health: Dict[str, Any],
        blockers: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        edge_summary = edge_snapshot.get("summary", {}) if isinstance(edge_snapshot, dict) else {}
        blocker_codes = [str(item.get("code", "") or "") for item in blockers if isinstance(item, dict)]
        supported_symbols = list(edge_summary.get("supported_symbols", []) or [])
        replay_acceptance_any = bool(edge_summary.get("replay_acceptance_any", False))
        recent_ready_runs = int(runtime_swarm_health.get("recent_ready_runs", 0) or 0)
        recent_runs_considered = int(runtime_swarm_health.get("recent_runs_considered", 0) or 0)
        total_pnl = float(performance_summary.get("total_pnl", 0.0) or 0.0)
        positive_timeframes = [
            str(item["timeframe"])
            for item in self._summarize_timeframe_pnl(performance_summary).get("positive", [])
            if isinstance(item, dict)
        ]

        requirements: List[str] = []
        if "runtime_swarm_unavailable" in blocker_codes or recent_ready_runs <= 0:
            requirements.append("Restore runtime consensus so at least one recent run is genuinely swarm-ready.")
        if "latest_runtime_inventory_blocked" in blocker_codes:
            requirements.append(
                "Increase short-horizon ETH inventory quality or discovery so the latest runtime scan returns tradeable markets."
            )
        if "single_provider_control" in blocker_codes:
            requirements.append("Restore multi-provider runtime health so ETH analysis is not xAI-only control.")
        if "no_holdout_support" in blocker_codes or not replay_acceptance_any:
            requirements.append("Earn filtered holdout support and a replay-accepted variant before deployment.")
        if "positive_lane_low_sample" in blocker_codes:
            requirements.append(
                f"Increase the only positive lane beyond the {MIN_RESEARCH_CANDIDATE_TRADES}-trade research bar."
            )
        if "positive_patch_non_independent" in blocker_codes:
            requirements.append(
                "Find a positive ETH patch that survives without one outsized winner and spans more distinct markets before treating it as edge."
            )
        if "negative_realized_book" in blocker_codes or total_pnl < 0.0:
            requirements.append("Improve the realized ETH book from negative to durable positive territory.")
        if "high_confidence_anti_signal" in blocker_codes:
            requirements.append("Recalibrate confidence so the >=50% cohort stops losing before using conviction as an edge amplifier.")
        if "yes_direction_anti_signal" in blocker_codes:
            requirements.append("Repair directional bias so YES-side calls stop behaving like anti-signal before trusting the swarm on binary direction.")
        if "strict_inventory_empty" in blocker_codes:
            requirements.append("Fix strict ETH inventory sourcing so production-style scans return candidates.")
        if not requirements:
            requirements.append("Maintain the current safety gates and continue measuring ETH performance.")

        approved_symbols = supported_symbols if not blocker_codes else []
        if "BTC" in approved_symbols and not replay_acceptance_any:
            approved_symbols = [sym for sym in approved_symbols if sym != "BTC"]

        return {
            "status": "GO" if not blocker_codes else "NO_GO",
            "deployable_now": not bool(blocker_codes),
            "deployment_target": "attended_micro_cap",
            "current_scope": "research_only" if blocker_codes else "attended_micro_cap",
            "approved_symbols": approved_symbols,
            "btc_allowed": bool("BTC" in approved_symbols),
            "arbitrage_policy": "structural_only",
            "reason_codes": blocker_codes,
            "positive_timeframes": positive_timeframes,
            "recent_runtime_ready_runs": recent_ready_runs,
            "recent_runtime_runs_considered": recent_runs_considered,
            "requirements": requirements,
        }

    def build_risk_return_snapshot(self, performance_summary: Dict[str, Any]) -> Dict[str, Any]:
        perf = performance_summary if isinstance(performance_summary, dict) else {}
        closed_trades = int(perf.get("closed_trades", 0) or 0)
        total_pnl = float(perf.get("total_pnl", 0.0) or 0.0)
        avg_win = float(perf.get("avg_win", 0.0) or 0.0)
        avg_loss = float(perf.get("avg_loss", 0.0) or 0.0)
        max_drawdown = float(perf.get("max_drawdown", 0.0) or 0.0)
        by_timeframe = perf.get("by_timeframe", {}) if isinstance(perf, dict) else {}

        expectancy_per_closed_trade = (total_pnl / closed_trades) if closed_trades > 0 else 0.0
        payoff_ratio = (abs(avg_win / avg_loss) if avg_loss < 0 else None)
        pnl_to_drawdown = (total_pnl / max_drawdown) if max_drawdown > 0 else None

        ranked_timeframes: List[Dict[str, Any]] = []
        for timeframe, stats in (by_timeframe or {}).items():
            if not isinstance(stats, dict):
                continue
            ranked_timeframes.append(
                {
                    "timeframe": str(timeframe),
                    "pnl": round(float(stats.get("pnl", 0.0) or 0.0), 2),
                    "count": int(stats.get("count", 0) or 0),
                    "win_rate": round(float(stats.get("win_rate", 0.0) or 0.0), 3),
                }
            )
        ranked_timeframes.sort(key=lambda item: (item["pnl"], item["count"]), reverse=True)
        best_timeframe = ranked_timeframes[0] if ranked_timeframes else {}
        worst_timeframe = ranked_timeframes[-1] if ranked_timeframes else {}

        return {
            "closed_trades": closed_trades,
            "total_pnl": round(total_pnl, 2),
            "expectancy_per_closed_trade": round(expectancy_per_closed_trade, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "payoff_ratio": round(payoff_ratio, 2) if payoff_ratio is not None else None,
            "max_drawdown": round(max_drawdown, 2),
            "pnl_to_drawdown": round(pnl_to_drawdown, 2) if pnl_to_drawdown is not None else None,
            "best_timeframe": best_timeframe,
            "worst_timeframe": worst_timeframe,
        }

    def build_calibration_snapshot(self, performance_summary: Dict[str, Any]) -> Dict[str, Any]:
        perf = performance_summary if isinstance(performance_summary, dict) else {}
        confidence = perf.get("confidence_diagnostics", {}) if isinstance(perf, dict) else {}
        high = confidence.get("high_confidence", {}) if isinstance(confidence, dict) else {}
        severe = confidence.get("severe_confidence", {}) if isinstance(confidence, dict) else {}
        low = confidence.get("low_confidence", {}) if isinstance(confidence, dict) else {}

        return {
            "verdict": str(confidence.get("verdict", "unknown") or "unknown"),
            "consensus_accuracy": round(float(perf.get("consensus_accuracy", 0.0) or 0.0), 3),
            "brier_score": round(float(perf.get("brier_score", 0.0) or 0.0), 4),
            "mean_absolute_error": round(float(perf.get("mean_absolute_error", 0.0) or 0.0), 4),
            "high_confidence_threshold": float(confidence.get("high_confidence_threshold", 0.5) or 0.5),
            "severe_confidence_threshold": float(confidence.get("severe_confidence_threshold", 0.7) or 0.7),
            "high_confidence": {
                "count": int(high.get("count", 0) or 0),
                "win_rate": round(float(high.get("win_rate", 0.0) or 0.0), 3),
                "total_pnl": round(float(high.get("total_pnl", 0.0) or 0.0), 2),
                "avg_predicted_probability": round(float(high.get("avg_predicted_probability", 0.0) or 0.0), 3),
                "overconfidence_gap": round(float(high.get("overconfidence_gap", 0.0) or 0.0), 3),
            },
            "severe_confidence": {
                "count": int(severe.get("count", 0) or 0),
                "win_rate": round(float(severe.get("win_rate", 0.0) or 0.0), 3),
                "total_pnl": round(float(severe.get("total_pnl", 0.0) or 0.0), 2),
                "avg_predicted_probability": round(float(severe.get("avg_predicted_probability", 0.0) or 0.0), 3),
                "overconfidence_gap": round(float(severe.get("overconfidence_gap", 0.0) or 0.0), 3),
            },
            "low_confidence": {
                "count": int(low.get("count", 0) or 0),
                "win_rate": round(float(low.get("win_rate", 0.0) or 0.0), 3),
                "total_pnl": round(float(low.get("total_pnl", 0.0) or 0.0), 2),
                "avg_predicted_probability": round(float(low.get("avg_predicted_probability", 0.0) or 0.0), 3),
                "overconfidence_gap": round(float(low.get("overconfidence_gap", 0.0) or 0.0), 3),
            },
            "best_cap": self._normalize_confidence_gate_row(confidence.get("best_cap", {})),
            "best_floor": self._normalize_confidence_gate_row(confidence.get("best_floor", {})),
            "gate_verdict": self._normalize_confidence_gate_verdict(confidence.get("gate_verdict", {})),
            "cap_sweep": [self._normalize_confidence_gate_row(row) for row in (confidence.get("cap_sweep", []) or []) if isinstance(row, dict)],
            "floor_sweep": [self._normalize_confidence_gate_row(row) for row in (confidence.get("floor_sweep", []) or []) if isinstance(row, dict)],
            "confidence_monotonicity_broken": bool(confidence.get("confidence_monotonicity_broken", False)),
        }

    def build_edge_quality_snapshot(self, performance_summary: Dict[str, Any]) -> Dict[str, Any]:
        perf = performance_summary if isinstance(performance_summary, dict) else {}
        edge_quality = perf.get("edge_quality_diagnostics", {}) if isinstance(perf, dict) else {}
        return {
            "verdict": str(edge_quality.get("verdict", "unknown") or "unknown"),
            "min_trade_count": int(edge_quality.get("min_trade_count", 0) or 0),
            "best_cap": self._normalize_edge_gate_row(edge_quality.get("best_cap", {})),
            "best_floor": self._normalize_edge_gate_row(edge_quality.get("best_floor", {})),
            "best_low_sample_floor": self._normalize_edge_gate_row(edge_quality.get("best_low_sample_floor", {})),
            "low_edge": self._normalize_edge_gate_row(edge_quality.get("low_edge", {})),
            "high_edge": self._normalize_edge_gate_row(edge_quality.get("high_edge", {})),
            "high_edge_beats_low_edge": bool(edge_quality.get("high_edge_beats_low_edge", False)),
            "gate_verdict": self._normalize_confidence_gate_verdict(edge_quality.get("gate_verdict", {})),
            "cap_sweep": [
                self._normalize_edge_gate_row(row)
                for row in (edge_quality.get("cap_sweep", []) or [])
                if isinstance(row, dict)
            ],
            "floor_sweep": [
                self._normalize_edge_gate_row(row)
                for row in (edge_quality.get("floor_sweep", []) or [])
                if isinstance(row, dict)
            ],
        }

    def build_edge_timeframe_snapshot(self, performance_summary: Dict[str, Any]) -> Dict[str, Any]:
        perf = performance_summary if isinstance(performance_summary, dict) else {}
        diagnostics = perf.get("edge_timeframe_diagnostics", {}) if isinstance(perf, dict) else {}
        return {
            "verdict": str(diagnostics.get("verdict", "unknown") or "unknown"),
            "min_trade_count": int(diagnostics.get("min_trade_count", 0) or 0),
            "gate_verdict": self._normalize_confidence_gate_verdict(diagnostics.get("gate_verdict", {})),
            "best_sampled_pocket": self._normalize_edge_timeframe_row(diagnostics.get("best_sampled_pocket", {})),
            "best_low_sample_pocket": self._normalize_edge_timeframe_row(diagnostics.get("best_low_sample_pocket", {})),
            "top_rows": [
                self._normalize_edge_timeframe_row(row)
                for row in (diagnostics.get("top_rows", []) or [])
                if isinstance(row, dict)
            ],
            "positive_sampled_pocket_count": int(diagnostics.get("positive_sampled_pocket_count", 0) or 0),
            "positive_low_sample_pocket_count": int(diagnostics.get("positive_low_sample_pocket_count", 0) or 0),
        }

    def build_market_archetype_snapshot(self, performance_summary: Dict[str, Any]) -> Dict[str, Any]:
        perf = performance_summary if isinstance(performance_summary, dict) else {}
        diagnostics = perf.get("market_archetype_diagnostics", {}) if isinstance(perf, dict) else {}
        return {
            "verdict": str(diagnostics.get("verdict", "unknown") or "unknown"),
            "min_trade_count": int(diagnostics.get("min_trade_count", 0) or 0),
            "gate_verdict": self._normalize_confidence_gate_verdict(diagnostics.get("gate_verdict", {})),
            "best_sampled_pocket": self._normalize_market_archetype_row(diagnostics.get("best_sampled_pocket", {})),
            "best_low_sample_pocket": self._normalize_market_archetype_row(diagnostics.get("best_low_sample_pocket", {})),
            "top_rows": [
                self._normalize_market_archetype_row(row)
                for row in (diagnostics.get("top_rows", []) or [])
                if isinstance(row, dict)
            ],
            "positive_sampled_pocket_count": int(diagnostics.get("positive_sampled_pocket_count", 0) or 0),
            "positive_low_sample_pocket_count": int(diagnostics.get("positive_low_sample_pocket_count", 0) or 0),
        }

    def build_entry_price_snapshot(self, performance_summary: Dict[str, Any]) -> Dict[str, Any]:
        perf = performance_summary if isinstance(performance_summary, dict) else {}
        diagnostics = perf.get("entry_price_diagnostics", {}) if isinstance(perf, dict) else {}
        best_low_sample_concentration = self._normalize_patch_concentration_row(diagnostics.get("best_low_sample_concentration", {}))
        cheap_tail_bullish_no_fast_concentration = self._normalize_patch_concentration_row(diagnostics.get("cheap_tail_bullish_no_fast_concentration", {}))
        return {
            "verdict": str(diagnostics.get("verdict", "unknown") or "unknown"),
            "min_trade_count": int(diagnostics.get("min_trade_count", 0) or 0),
            "gate_verdict": self._normalize_confidence_gate_verdict(diagnostics.get("gate_verdict", {})),
            "best_sampled_pocket": self._normalize_entry_price_row(diagnostics.get("best_sampled_pocket", {})),
            "best_low_sample_pocket": self._normalize_entry_price_row(diagnostics.get("best_low_sample_pocket", {})),
            "cheap_tail_all": self._normalize_entry_price_row(diagnostics.get("cheap_tail_all", {})),
            "cheap_tail_bullish_no": self._normalize_entry_price_row(diagnostics.get("cheap_tail_bullish_no", {})),
            "cheap_tail_bullish_no_fast": self._normalize_entry_price_row(diagnostics.get("cheap_tail_bullish_no_fast", {})),
            "best_low_sample_concentration": best_low_sample_concentration,
            "cheap_tail_bullish_no_fast_concentration": cheap_tail_bullish_no_fast_concentration,
            "best_low_sample_independence_verdict": self._build_patch_independence_verdict(best_low_sample_concentration),
            "cheap_tail_bullish_no_fast_independence_verdict": self._build_patch_independence_verdict(cheap_tail_bullish_no_fast_concentration),
            "top_rows": [
                self._normalize_entry_price_row(row)
                for row in (diagnostics.get("top_rows", []) or [])
                if isinstance(row, dict)
            ],
            "positive_sampled_pocket_count": int(diagnostics.get("positive_sampled_pocket_count", 0) or 0),
            "positive_low_sample_pocket_count": int(diagnostics.get("positive_low_sample_pocket_count", 0) or 0),
        }

    def build_surviving_patch_snapshot(
        self,
        entry_price_snapshot: Dict[str, Any],
        symbol_verdicts: Dict[str, Any],
    ) -> Dict[str, Any]:
        snapshot = entry_price_snapshot if isinstance(entry_price_snapshot, dict) else {}
        verdicts = symbol_verdicts if isinstance(symbol_verdicts, dict) else {}
        eth_verdict = verdicts.get("ETH", {}) if isinstance(verdicts, dict) else {}
        patch = snapshot.get("best_low_sample_pocket", {}) if isinstance(snapshot, dict) else {}
        concentration = snapshot.get("best_low_sample_concentration", {}) if isinstance(snapshot, dict) else {}
        independence = snapshot.get("best_low_sample_independence_verdict", {}) if isinstance(snapshot, dict) else {}
        research_bar = int(snapshot.get("min_trade_count", 0) or 0)
        patch_count = int(patch.get("count", 0) or 0)
        patch_pnl = round(float(patch.get("total_pnl", 0.0) or 0.0), 2)
        patch_found = bool(patch) and patch_count > 0 and patch_pnl > 0.0

        promotability = {
            "status": "NO_POSITIVE_PATCH",
            "reason_codes": ["no_positive_low_sample_patch"],
        }
        status = "NO_POSITIVE_PATCH"
        if patch_found:
            status = "PATCH_FOUND"
            independence_status = str(independence.get("status", "unknown") or "unknown")
            independence_reasons = list(independence.get("reason_codes", []) or [])
            if independence_status == "NON_INDEPENDENT_PATCH":
                promotability = {
                    "status": "RESEARCH_ONLY_NON_INDEPENDENT",
                    "reason_codes": independence_reasons,
                }
            elif 0 < patch_count < research_bar:
                promotability = {
                    "status": "RESEARCH_ONLY_LOW_SAMPLE",
                    "reason_codes": ["below_research_bar"],
                }
            elif (
                str(eth_verdict.get("status", "UNKNOWN") or "UNKNOWN") == "APPROVED"
                and str(eth_verdict.get("edge_status", "unknown") or "unknown") == "confirmed_positive_edge"
            ):
                promotability = {
                    "status": "PROMOTABLE",
                    "reason_codes": [],
                }
            else:
                promotability = {
                    "status": "RESEARCH_ONLY_UNCONFIRMED",
                    "reason_codes": ["not_approved_for_deployment"],
                }

        return {
            "status": status,
            "symbol": "ETH",
            "research_bar": research_bar,
            "patch": patch if patch_found else {},
            "concentration": concentration if patch_found else {},
            "independence_verdict": independence if patch_found else {},
            "promotability": promotability,
            "eth_symbol_status": str(eth_verdict.get("status", "UNKNOWN") or "UNKNOWN"),
            "eth_edge_status": str(eth_verdict.get("edge_status", "unknown") or "unknown"),
        }

    def build_active_edge_snapshot(
        self,
        edge_snapshot: Dict[str, Any],
        surviving_patch_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        snapshot = edge_snapshot if isinstance(edge_snapshot, dict) else {}
        summary = snapshot.get("summary", {}) if isinstance(snapshot, dict) else {}
        variants = snapshot.get("variants", {}) if isinstance(snapshot, dict) else {}
        surviving = surviving_patch_snapshot if isinstance(surviving_patch_snapshot, dict) else {}

        best_label = str(summary.get("best_exploratory_variant_by_score", "unknown") or "unknown")
        variant_payload = variants.get(best_label, {}) if isinstance(variants, dict) else {}
        score = variant_payload.get("score", {}) if isinstance(variant_payload, dict) else {}
        replay_payload = variant_payload.get("replay", {}) if isinstance(variant_payload, dict) else {}
        best_active_configuration = {
            "label": best_label,
            "filtered_trades": int(score.get("filtered_trades", 0) or 0),
            "total_pnl": round(float(score.get("total_pnl", 0.0) or 0.0), 2),
            "score": round(float(score.get("score", 0.0) or 0.0), 2),
            "replay_accepted": bool(replay_payload.get("accepted", False)),
            "holdout_trades": int(replay_payload.get("holdout", {}).get("filtered_trades", 0) or 0),
        }
        unique_configurations: List[Dict[str, Any]] = []
        seen_signatures: set[str] = set()
        for label, payload in (variants.items() if isinstance(variants, dict) else []):
            if not isinstance(payload, dict):
                continue
            params = payload.get("params", {})
            if not isinstance(params, dict):
                continue
            signature = json.dumps(params, sort_keys=True, default=str)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            active_score = payload.get("score", {}) if isinstance(payload, dict) else {}
            active_replay = payload.get("replay", {}) if isinstance(payload, dict) else {}
            unique_configurations.append(
                {
                    "label": str(label or "unknown"),
                    "filtered_trades": int(active_score.get("filtered_trades", 0) or 0),
                    "total_pnl": round(float(active_score.get("total_pnl", 0.0) or 0.0), 2),
                    "score": round(float(active_score.get("score", 0.0) or 0.0), 2),
                    "replay_accepted": bool(active_replay.get("accepted", False)),
                    "holdout_trades": int(active_replay.get("holdout", {}).get("filtered_trades", 0) or 0),
                }
            )
        positive_active_configurations = [
            row for row in unique_configurations if float(row.get("total_pnl", 0.0) or 0.0) > 0.0
        ]
        replay_accepted_active_configurations = [
            row for row in unique_configurations if bool(row.get("replay_accepted", False))
        ]
        positive_replay_accepted_active_configurations = [
            row
            for row in positive_active_configurations
            if bool(row.get("replay_accepted", False))
        ]
        best_positive_active_configuration = (
            max(positive_active_configurations, key=lambda row: float(row.get("score", 0.0) or 0.0))
            if positive_active_configurations
            else {}
        )

        patch_found = bool(surviving.get("patch"))
        promotability = surviving.get("promotability", {}) if isinstance(surviving, dict) else {}
        promotability_status = str(promotability.get("status", "unknown") or "unknown")
        active_positive = float(best_active_configuration.get("total_pnl", 0.0) or 0.0) > 0.0
        active_replay_accepted = bool(best_active_configuration.get("replay_accepted", False))

        reason_codes: List[str] = []
        if not active_positive:
            reason_codes.append("best_active_configuration_negative_or_flat")
        if not active_replay_accepted:
            reason_codes.append("best_active_configuration_not_replay_accepted")
        if patch_found:
            reason_codes.append("surviving_patch_is_slice_not_configuration")
        if promotability_status != "PROMOTABLE":
            reason_codes.append("surviving_patch_not_promotable")

        if active_positive and active_replay_accepted and promotability_status == "PROMOTABLE":
            status = "PROMOTABLE_ACTIVE_EDGE"
        elif active_positive and not active_replay_accepted:
            status = "POSITIVE_CONFIG_UNCONFIRMED"
        elif patch_found:
            status = "PATCH_ONLY_NON_PROMOTABLE"
        else:
            status = "NO_POSITIVE_ACTIVE_EDGE"

        return {
            "status": status,
            "best_active_configuration": best_active_configuration,
            "positive_active_configuration_count": len(positive_active_configurations),
            "replay_accepted_active_configuration_count": len(replay_accepted_active_configurations),
            "positive_replay_accepted_active_configuration_count": len(positive_replay_accepted_active_configurations),
            "best_positive_active_configuration": best_positive_active_configuration,
            "surviving_patch_found": patch_found,
            "surviving_patch_promotability": promotability,
            "reason_codes": reason_codes,
        }

    def build_runtime_regime_snapshot(
        self,
        runtime_swarm_health: Dict[str, Any],
        blockers: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        runtime = runtime_swarm_health if isinstance(runtime_swarm_health, dict) else {}
        blocker_codes = {
            str(item.get("code", "") or "")
            for item in (blockers or [])
            if isinstance(item, dict)
        }
        latest_scan = runtime.get("latest_runtime_scan_summary", {}) if isinstance(runtime, dict) else {}
        latest_cycle = runtime.get("latest_cycle_interpretation", {}) if isinstance(runtime, dict) else {}
        provider = runtime.get("runtime_provider_verdict", {}) if isinstance(runtime, dict) else {}
        recent_primary_cause_counts = runtime.get("recent_primary_cause_counts", {}) if isinstance(runtime, dict) else {}
        most_common_recent_primary_cause = str(runtime.get("most_common_recent_primary_cause", "") or "")

        latest_blocker_code = "none"
        latest_blocker = "none"
        if str(latest_scan.get("status", "") or "") == "NO_TRADEABLE_MARKETS_IN_LATEST_RUNTIME_SCAN":
            latest_blocker_code = "inventory_blocked"
            latest_blocker = self._format_runtime_scan_summary(latest_scan)
        elif isinstance(latest_cycle, dict) and latest_cycle:
            latest_blocker_code = "cycle_blocked"
            latest_blocker = self._format_runtime_cycle_interpretation(latest_cycle)
        elif isinstance(provider, dict) and provider:
            latest_blocker_code = "provider_blocked"
            latest_blocker = self._format_runtime_provider_verdict(provider)

        chronic_blocker_code = "none"
        chronic_blocker = "none"
        if "runtime_swarm_unavailable" in blocker_codes:
            chronic_blocker_code = "provider_blocked"
            chronic_blocker = self._format_runtime_provider_verdict(provider)
        elif "single_provider_control" in blocker_codes:
            chronic_blocker_code = "single_provider_control"
            chronic_blocker = self._format_runtime_provider_verdict(provider)

        status_parts: List[str] = []
        if latest_blocker_code != "none":
            status_parts.append(f"LATEST_{latest_blocker_code.upper()}")
        if chronic_blocker_code != "none":
            status_parts.append(f"CHRONIC_{chronic_blocker_code.upper()}")
        status = "__".join(status_parts) if status_parts else "NO_RUNTIME_BLOCKER_CLASSIFIED"

        return {
            "status": status,
            "latest_blocker_code": latest_blocker_code,
            "latest_blocker": latest_blocker,
            "chronic_blocker_code": chronic_blocker_code,
            "chronic_blocker": chronic_blocker,
            "recent_primary_cause_counts": dict(recent_primary_cause_counts) if isinstance(recent_primary_cause_counts, dict) else {},
            "recent_primary_cause_counted_runs": int(runtime.get("recent_primary_cause_counted_runs", 0) or 0),
            "most_common_recent_primary_cause": most_common_recent_primary_cause,
            "recent_runtime_dirs_considered": int(runtime.get("recent_runtime_dirs_considered", 0) or 0),
            "recent_prediction_runs_considered": int(runtime.get("recent_prediction_runs_considered", 0) or 0),
            "recent_runs_considered": int(runtime.get("recent_runs_considered", 0) or 0),
            "recent_ready_runs": int(runtime.get("recent_ready_runs", 0) or 0),
            "historical_runs_considered": int(runtime.get("historical_runs_considered", 0) or 0),
            "historical_ready_runs": int(runtime.get("historical_ready_runs", 0) or 0),
        }

    def build_direction_snapshot(self, performance_summary: Dict[str, Any]) -> Dict[str, Any]:
        perf = performance_summary if isinstance(performance_summary, dict) else {}
        direction = perf.get("direction_diagnostics", {}) if isinstance(perf, dict) else {}
        by_direction = direction.get("by_direction", {}) if isinstance(direction, dict) else {}
        best_direction = direction.get("best_direction", {}) if isinstance(direction, dict) else {}
        gate_verdict = direction.get("gate_verdict", {}) if isinstance(direction, dict) else {}
        best_direction_timeframe = direction.get("best_direction_timeframe", {}) if isinstance(direction, dict) else {}
        worst_direction_timeframe = direction.get("worst_direction_timeframe", {}) if isinstance(direction, dict) else {}
        top_negative_direction_timeframes = direction.get("top_negative_direction_timeframes", []) if isinstance(direction, dict) else []
        exclusion_rescue = direction.get("exclusion_rescue", {}) if isinstance(direction, dict) else {}
        pocket_verdict = direction.get("pocket_verdict", {}) if isinstance(direction, dict) else {}
        return {
            "verdict": str(direction.get("verdict", "unknown") or "unknown"),
            "gate_verdict": self._normalize_confidence_gate_verdict(gate_verdict),
            "yes": self._normalize_direction_row(by_direction.get("YES", {})),
            "no": self._normalize_direction_row(by_direction.get("NO", {})),
            "abstain": self._normalize_direction_row(by_direction.get("ABSTAIN", {})),
            "best_direction": {
                "direction": str(best_direction.get("direction", "") or ""),
                **self._normalize_direction_row(best_direction),
            } if best_direction else {},
            "best_direction_timeframe": {
                "direction": str(best_direction_timeframe.get("direction", "") or ""),
                "timeframe": str(best_direction_timeframe.get("timeframe", "") or ""),
                **self._normalize_direction_row(best_direction_timeframe),
            } if best_direction_timeframe else {},
            "worst_direction_timeframe": {
                "direction": str(worst_direction_timeframe.get("direction", "") or ""),
                "timeframe": str(worst_direction_timeframe.get("timeframe", "") or ""),
                **self._normalize_direction_row(worst_direction_timeframe),
                "drag_share_of_negative_loss": round(float(worst_direction_timeframe.get("drag_share_of_negative_loss", 0.0) or 0.0), 3),
            } if worst_direction_timeframe else {},
            "top_negative_direction_timeframes": [
                {
                    "direction": str(row.get("direction", "") or ""),
                    "timeframe": str(row.get("timeframe", "") or ""),
                    **self._normalize_direction_row(row),
                    "drag_share_of_negative_loss": round(float(row.get("drag_share_of_negative_loss", 0.0) or 0.0), 3),
                }
                for row in (top_negative_direction_timeframes or [])
                if isinstance(row, dict)
            ],
            "top_two_directional_drag_share": round(float(direction.get("top_two_directional_drag_share", 0.0) or 0.0), 3),
            "exclusion_rescue": {
                "status": str(exclusion_rescue.get("status", "unknown") or "unknown"),
                "reason_codes": list(exclusion_rescue.get("reason_codes", []) or []),
                "scenarios": [
                    {
                        "label": str(row.get("label", "") or ""),
                        "excluded_keys": list(row.get("excluded_keys", []) or []),
                        "removed_count": int(row.get("removed_count", 0) or 0),
                        "removed_pnl": round(float(row.get("removed_pnl", 0.0) or 0.0), 2),
                        "residual_pnl": round(float(row.get("residual_pnl", 0.0) or 0.0), 2),
                    }
                    for row in (exclusion_rescue.get("scenarios", []) or [])
                    if isinstance(row, dict)
                ],
            },
            "pocket_verdict": self._normalize_confidence_gate_verdict(pocket_verdict),
        }

    def build_policy_rescue_snapshot(self, performance_summary: Dict[str, Any]) -> Dict[str, Any]:
        perf = performance_summary if isinstance(performance_summary, dict) else {}
        policy = perf.get("policy_rescue_diagnostics", {}) if isinstance(perf, dict) else {}
        return {
            "verdict": str(policy.get("verdict", "unknown") or "unknown"),
            "min_trade_count": int(policy.get("min_trade_count", 0) or 0),
            "gate_verdict": self._normalize_confidence_gate_verdict(policy.get("gate_verdict", {})),
            "best_sampled_policy": self._normalize_policy_rescue_row(policy.get("best_sampled_policy", {})),
            "best_low_sample_policy": self._normalize_policy_rescue_row(policy.get("best_low_sample_policy", {})),
            "top_rows": [
                self._normalize_policy_rescue_row(row)
                for row in (policy.get("top_rows", []) or [])
                if isinstance(row, dict)
            ],
            "positive_sampled_policy_count": int(policy.get("positive_sampled_policy_count", 0) or 0),
            "positive_low_sample_policy_count": int(policy.get("positive_low_sample_policy_count", 0) or 0),
        }

    def build_symbol_verdicts(
        self,
        edge_snapshot: Dict[str, Any],
        performance_summary: Dict[str, Any],
        runtime_swarm_health: Dict[str, Any],
        deployment_verdict: Dict[str, Any],
    ) -> Dict[str, Any]:
        variants = edge_snapshot.get("variants", {}) if isinstance(edge_snapshot, dict) else {}
        summary = edge_snapshot.get("summary", {}) if isinstance(edge_snapshot, dict) else {}
        experiment_matrix = edge_snapshot.get("experiment_matrix", {}) if isinstance(edge_snapshot, dict) else {}
        supported_symbols = set(summary.get("supported_symbols", []) or [])
        approved_symbols = set(deployment_verdict.get("approved_symbols", []) or [])
        deployment_reason_codes = set(deployment_verdict.get("reason_codes", []) or [])
        replay = performance_summary.get("replay", {}) if isinstance(performance_summary, dict) else {}
        recent_runs_considered = int(runtime_swarm_health.get("recent_runs_considered", 0) or 0)
        recent_ready_runs = int(runtime_swarm_health.get("recent_ready_runs", 0) or 0)
        single_provider_only_rate = float(runtime_swarm_health.get("single_provider_only_rate", 0.0) or 0.0)
        realized_total_pnl = float(performance_summary.get("total_pnl", 0.0) or 0.0)

        verdicts: Dict[str, Any] = {}
        for symbol, variant_key in (("ETH", "eth_only"), ("BTC", "btc_only")):
            variant_payload = variants.get(variant_key, {}) if isinstance(variants, dict) else {}
            score = variant_payload.get("score", {}) if isinstance(variant_payload, dict) else {}
            replay_payload = variant_payload.get("replay", {}) if isinstance(variant_payload, dict) else {}
            current_lane = {
                "variant": variant_key,
                "filtered_trades": int(score.get("filtered_trades", 0) or 0),
                "total_pnl": round(float(score.get("total_pnl", 0.0) or 0.0), 2),
                "score": round(float(score.get("score", 0.0) or 0.0), 2),
                "replay_accepted": bool(replay_payload.get("accepted", False)),
                "holdout_trades": int(replay_payload.get("holdout", {}).get("filtered_trades", 0) or 0),
            }
            best_measured_positive_lane = self._best_symbol_candidate(
                experiment_matrix.get("positive_candidates", []),
                symbol,
            )
            best_low_sample_positive_lane = self._best_symbol_candidate(
                experiment_matrix.get("low_sample_candidates", []),
                symbol,
            )

            if symbol in approved_symbols and current_lane["replay_accepted"] and current_lane["total_pnl"] > 0.0:
                edge_status = "confirmed_positive_edge"
                status = "APPROVED"
            elif best_measured_positive_lane:
                edge_status = "measured_positive_unconfirmed"
                status = "RESEARCH_ONLY"
            elif best_low_sample_positive_lane:
                edge_status = (
                    "non_independent_low_sample_patch"
                    if symbol == "ETH" and "positive_patch_non_independent" in deployment_reason_codes
                    else "low_sample_positive_patch"
                )
                status = "RESEARCH_ONLY"
            elif current_lane["filtered_trades"] > 0 or current_lane["total_pnl"] != 0.0:
                edge_status = "negative_or_flat_current_lane"
                status = "RESEARCH_ONLY"
            else:
                edge_status = "no_measured_edge"
                status = "RESEARCH_ONLY"

            reason_codes: List[str] = []
            if symbol not in approved_symbols:
                reason_codes.append(f"{symbol.lower()}_not_approved")
            if symbol not in supported_symbols:
                reason_codes.append(f"{symbol.lower()}_not_supported")
            if not current_lane["replay_accepted"]:
                reason_codes.append("no_replay_acceptance")
            if current_lane["holdout_trades"] <= 0:
                reason_codes.append("no_filtered_holdout_trades")
            if current_lane["filtered_trades"] <= 0:
                reason_codes.append("no_current_filtered_trades")
            elif current_lane["total_pnl"] < 0.0:
                reason_codes.append("negative_current_lane")
            if best_measured_positive_lane and not bool(best_measured_positive_lane.get("replay_accepted", False)):
                reason_codes.append("best_positive_lane_unconfirmed")
            elif best_low_sample_positive_lane:
                reason_codes.append("positive_lane_low_sample")
            elif not best_measured_positive_lane:
                reason_codes.append("no_positive_measured_lane")
            if symbol == "ETH" and recent_runs_considered > 0 and recent_ready_runs <= 0:
                reason_codes.append("runtime_swarm_unavailable")
            if symbol == "ETH" and recent_runs_considered > 0 and single_provider_only_rate >= 0.8:
                reason_codes.append("single_provider_control")
            if symbol == "ETH" and "positive_patch_non_independent" in deployment_reason_codes:
                reason_codes.append("positive_patch_non_independent")
            if symbol == "ETH" and realized_total_pnl < 0.0:
                reason_codes.append("negative_realized_book")

            verdicts[symbol] = {
                "status": status,
                "approved_now": symbol in approved_symbols,
                "supported_today": symbol in supported_symbols,
                "edge_status": edge_status,
                "current_lane": current_lane,
                "best_measured_positive_lane": best_measured_positive_lane,
                "best_low_sample_positive_lane": best_low_sample_positive_lane,
                "reason_codes": reason_codes,
                "active_replay_gate_accepted": bool(replay.get("accepted", False)),
            }

        return verdicts

    def build_inventory_diagnostics(self, inventory_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        refresh_mode = str(inventory_snapshot.get("refresh_mode", "unknown") or "unknown")
        source_generated_at = str(inventory_snapshot.get("source_generated_at", "") or "")
        freshness_threshold_hours = 4.0
        snapshot_age_hours: Optional[float] = None
        fresh_enough_for_research_summary = False
        inventory_freshness_verdict = "unknown"
        source_generated_dt = self._parse_iso_datetime(source_generated_at)
        if refresh_mode == "live_scan":
            snapshot_age_hours = 0.0
            fresh_enough_for_research_summary = True
            inventory_freshness_verdict = "live_fresh"
        elif refresh_mode == "carried_forward":
            if source_generated_dt is not None:
                age_seconds = max(0.0, (datetime.now(timezone.utc) - source_generated_dt).total_seconds())
                snapshot_age_hours = round(age_seconds / 3600.0, 2)
                fresh_enough_for_research_summary = snapshot_age_hours <= freshness_threshold_hours
                inventory_freshness_verdict = (
                    "carried_forward_recent"
                    if fresh_enough_for_research_summary
                    else "carried_forward_stale"
                )
            else:
                inventory_freshness_verdict = "carried_forward_unknown_age"
        elif refresh_mode == "skipped_no_prior_snapshot":
            inventory_freshness_verdict = "no_inventory_snapshot"

        strict = inventory_snapshot.get("strict", {}) if isinstance(inventory_snapshot, dict) else {}
        broad = inventory_snapshot.get("broad", {}) if isinstance(inventory_snapshot, dict) else {}
        strict_tradeable = int(strict.get("tradeable_markets", 0) or 0)
        broad_tradeable = int(broad.get("tradeable_markets", 0) or 0)
        strict_symbol_expiry = strict.get("by_symbol_expiry_bucket", {}) if isinstance(strict, dict) else {}
        broad_symbol_expiry = broad.get("by_symbol_expiry_bucket", {}) if isinstance(broad, dict) else {}
        symbol_expiry_mix_available = bool(strict_symbol_expiry or broad_symbol_expiry)
        strict_share_of_broad = (
            round(strict_tradeable / broad_tradeable, 3) if broad_tradeable > 0 else None
        )
        broad_minus_strict = max(0, broad_tradeable - strict_tradeable)
        thesis_buckets = {"<=1h", "1-6h", "6-24h"}
        long_dated_buckets = {"1-3d", ">3d"}
        strict_eth_short_horizon = self._sum_symbol_expiry_counts(strict_symbol_expiry, "ETH", thesis_buckets)
        broad_eth_short_horizon = self._sum_symbol_expiry_counts(broad_symbol_expiry, "ETH", thesis_buckets)
        broad_btc_long_dated = self._sum_symbol_expiry_counts(broad_symbol_expiry, "BTC", long_dated_buckets)
        broad_eth_long_dated = self._sum_symbol_expiry_counts(broad_symbol_expiry, "ETH", long_dated_buckets)
        thesis_surface_share = (
            round(broad_eth_short_horizon / broad_tradeable, 3) if broad_tradeable > 0 else None
        )
        strict_thesis_capture_rate = (
            round(strict_eth_short_horizon / broad_eth_short_horizon, 3)
            if broad_eth_short_horizon > 0
            else None
        )
        btc_long_dated_to_eth_short_ratio = (
            round(broad_btc_long_dated / broad_eth_short_horizon, 3)
            if broad_eth_short_horizon > 0
            else None
        )
        strict_reasons = self._top_count_rows(
            strict.get("telemetry", {}).get("exclusion_reasons", {}) if isinstance(strict, dict) else {}
        )
        broad_reasons = self._top_count_rows(
            broad.get("telemetry", {}).get("exclusion_reasons", {}) if isinstance(broad, dict) else {}
        )
        broad_symbols = self._top_count_rows(
            broad.get("by_symbol", {}) if isinstance(broad, dict) else {},
            total_override=broad_tradeable,
            limit=10,
        )
        broad_expiry_buckets = self._top_count_rows(
            broad.get("by_expiry_bucket", {}) if isinstance(broad, dict) else {},
            total_override=broad_tradeable,
            limit=10,
        )
        dominant_broad_symbol = broad_symbols[0]["key"] if broad_symbols else ""
        dominant_broad_symbol_share = broad_symbols[0]["share"] if broad_symbols else None
        dominant_broad_expiry_bucket = broad_expiry_buckets[0]["key"] if broad_expiry_buckets else ""
        dominant_broad_expiry_share = broad_expiry_buckets[0]["share"] if broad_expiry_buckets else None

        if broad_tradeable <= 0:
            inventory_thesis = "No broad ETH/BTC market surface is currently visible."
        elif strict_tradeable <= 0:
            inventory_thesis = "Market surface exists, but production filters eliminate all current candidates."
        elif symbol_expiry_mix_available and broad_eth_short_horizon <= 0:
            inventory_thesis = "Visible surface exists, but there is effectively no short-horizon ETH inventory to trade."
        elif symbol_expiry_mix_available and broad_btc_long_dated > broad_eth_short_horizon:
            inventory_thesis = "Market surface exists, but the visible universe is dominated by long-dated BTC rather than short-horizon ETH."
        elif strict_tradeable < broad_tradeable:
            inventory_thesis = "Market surface exists, but strict production filters compress it sharply."
        else:
            inventory_thesis = "Strict production filters are preserving most of the visible market surface."

        return {
            "strict_tradeable_markets": strict_tradeable,
            "broad_tradeable_markets": broad_tradeable,
            "inventory_snapshot_age_hours": snapshot_age_hours,
            "inventory_freshness_threshold_hours": freshness_threshold_hours,
            "fresh_enough_for_research_summary": fresh_enough_for_research_summary,
            "inventory_freshness_verdict": inventory_freshness_verdict,
            "strict_share_of_broad": strict_share_of_broad,
            "broad_minus_strict_markets": broad_minus_strict,
            "symbol_expiry_mix_available": symbol_expiry_mix_available,
            "inventory_thesis": inventory_thesis,
            "strict_eth_short_horizon_markets": strict_eth_short_horizon,
            "broad_eth_short_horizon_markets": broad_eth_short_horizon,
            "broad_btc_long_dated_markets": broad_btc_long_dated,
            "broad_eth_long_dated_markets": broad_eth_long_dated,
            "thesis_surface_share_of_broad": thesis_surface_share,
            "strict_thesis_capture_rate": strict_thesis_capture_rate,
            "btc_long_dated_to_eth_short_ratio": btc_long_dated_to_eth_short_ratio,
            "top_strict_exclusion_reasons": strict_reasons,
            "top_broad_exclusion_reasons": broad_reasons,
            "dominant_broad_symbol": dominant_broad_symbol,
            "dominant_broad_symbol_share": dominant_broad_symbol_share,
            "dominant_broad_expiry_bucket": dominant_broad_expiry_bucket,
            "dominant_broad_expiry_share": dominant_broad_expiry_share,
        }

    def _resolve_data_dirs(self, data_dirs: Optional[List[str]]) -> List[str]:
        candidate_dirs = data_dirs or [str(self.config.data_dir)] + DEFAULT_RESEARCH_DATA_DIRS
        resolved: List[str] = []
        seen: set[str] = set()
        for item in candidate_dirs:
            path = Path(item)
            key = str(path.resolve()) if path.exists() else str(path)
            if key in seen:
                continue
            seen.add(key)
            if path.exists():
                resolved.append(str(path))
        return resolved

    def _config_summary(self) -> Dict[str, Any]:
        return {
            "data_dir": str(self.config.data_dir),
            "active_data_dirs": list(self.active_data_dirs),
            "archive_context_data_dirs": list(self.data_dirs),
            "search_symbols": list(self.config.search_symbols),
            "min_edge_threshold": float(self.config.min_edge_threshold),
            "min_edge_confidence": float(self.config.min_edge_confidence),
            "min_volume_24h_usd": float(self.config.min_volume_24h_usd),
            "min_liquidity_usd": float(self.config.min_liquidity_usd),
            "min_expiry_hours": self.config.min_expiry_hours,
            "max_expiry_hours": self.config.max_expiry_hours,
        }

    @staticmethod
    def _inventory_config_summary(config: PolymarketCLIConfig) -> Dict[str, Any]:
        return {
            "search_symbols": list(config.search_symbols),
            "min_liquidity_usd": float(config.min_liquidity_usd),
            "min_volume_24h_usd": float(config.min_volume_24h_usd),
            "min_expiry_hours": config.min_expiry_hours,
            "max_expiry_hours": config.max_expiry_hours,
        }

    @staticmethod
    def _supported_symbols(eth: Dict[str, Any], btc: Dict[str, Any]) -> List[str]:
        supported = []
        if float(eth.get("total_pnl", 0.0)) > 0.0 and float(eth.get("score", 0.0)) > 0.0:
            supported.append("ETH")
        if float(btc.get("total_pnl", 0.0)) > 0.0 and float(btc.get("score", 0.0)) > 0.0:
            supported.append("BTC")
        return supported

    @staticmethod
    def _best_symbol_candidate(candidates: Any, symbol: str) -> Dict[str, Any]:
        if not isinstance(candidates, list):
            return {}
        for item in candidates:
            if not isinstance(item, dict):
                continue
            params = item.get("params", {})
            if isinstance(params, dict) and params.get("allowed_symbols") == [symbol]:
                return item
        return {}

    @staticmethod
    def _expiry_bucket(hours_remaining: float) -> str:
        if hours_remaining <= 1:
            return "<=1h"
        if hours_remaining <= 6:
            return "1-6h"
        if hours_remaining <= 24:
            return "6-24h"
        if hours_remaining <= 72:
            return "1-3d"
        return ">3d"

    def _summarize_markets(self, markets: List[CLIMarket]) -> Dict[str, Any]:
        by_symbol: Counter[str] = Counter()
        by_type: Counter[str] = Counter()
        by_expiry: Counter[str] = Counter()
        by_symbol_expiry: Dict[str, Counter[str]] = defaultdict(Counter)

        for market in markets:
            symbol = str(market.symbol or "OTHER").upper()
            expiry_bucket = self._expiry_bucket(float(market.time_remaining_hours))
            by_symbol[symbol] += 1
            by_type[str(market.market_type or "unknown")] += 1
            by_expiry[expiry_bucket] += 1
            by_symbol_expiry[symbol][expiry_bucket] += 1

        return {
            "tradeable_markets": len(markets),
            "by_symbol": dict(by_symbol),
            "by_market_type": dict(by_type),
            "by_expiry_bucket": dict(by_expiry),
            "by_symbol_expiry_bucket": {
                symbol: dict(counter)
                for symbol, counter in sorted(by_symbol_expiry.items())
            },
            "sample_questions": [market.question for market in markets[:5]],
        }

    def _build_archive_context(self, base: ParamSet) -> Dict[str, Any]:
        if self._normalize_path_set(self.data_dirs) == self._normalize_path_set(self.active_data_dirs):
            return {
                "enabled": False,
                "data_dirs": list(self.data_dirs),
            }

        archive_score = self.archive_scorer.score(base)
        archive_replay = self.archive_scorer.score_replay(base)
        return {
            "enabled": True,
            "data_dirs": list(self.data_dirs),
            "current_config": {
                "score": archive_score.to_dict(),
                "replay": archive_replay.to_dict(),
            },
        }

    def _build_runtime_swarm_health(self) -> Dict[str, Any]:
        all_runtime_dirs = self._runtime_data_dirs_sorted(limit=None)
        runtime_dirs = all_runtime_dirs[:5]
        latest_dir = runtime_dirs[0] if runtime_dirs else None
        runtime_freshness_threshold_hours = 6.0
        if latest_dir is None:
            return {
                "ready": False,
                "status": "no_recent_runtime_artifacts",
                "runtime_freshness_verdict": "no_recent_runtime_artifacts",
                "latest_run_age_hours": None,
                "runtime_freshness_threshold_hours": runtime_freshness_threshold_hours,
                "fresh_enough_for_runtime_summary": False,
                "required_consensus_models": int(getattr(self.config, "min_consensus_count", 2)),
                "latest_data_dir": "",
                "total_runtime_dirs_scanned": 0,
                "recent_prediction_count": 0,
                "recent_runs_considered": 0,
                "recent_ready_runs": 0,
                "recent_degraded_runs": 0,
                "recent_data_dirs": [],
                "consensus_ready_runs_observed": 0,
                "consensus_ready_history_verdict": "no_recent_runtime_artifacts",
                "latest_consensus_ready_data_dir": "",
                "latest_consensus_ready_run_timestamp": "",
                "latest_consensus_ready_run_age_hours": None,
                "historical_runs_considered": 0,
                "historical_ready_runs": 0,
                "historical_degraded_runs": 0,
                "historical_run_error_code_counts": {},
                "historical_run_provider_status_counts": {},
                "historical_provider_ok_rates": {},
                "historical_healthy_provider_sets": {},
                "historical_single_provider_only_runs": 0,
                "historical_single_provider_only_rate": 0.0,
                "historical_xai_only_runs": 0,
                "historical_xai_only_rate": 0.0,
                "historical_zero_healthy_provider_runs": 0,
                "historical_zero_healthy_provider_rate": 0.0,
                "historical_other_provider_mix_runs": 0,
                "historical_other_provider_mix_rate": 0.0,
                "most_common_historical_healthy_provider_set": "",
                "latest_successful_model_count": 0,
                "recent_average_latest_successful_model_count": 0.0,
                "error_code_counts": {},
                "provider_status_counts": {},
            }

        run_audit = self._load_latest_run_audit(latest_dir)
        predictions = self._load_recent_predictions(latest_dir, limit=10)

        provider_status_counts: Dict[str, Dict[str, int]] = defaultdict(dict)
        error_code_counts: Counter[str] = Counter()
        abstain_reasons: Counter[str] = Counter()
        measurement_boundary_counts: Counter[str] = Counter()
        analysis_cohort_counts: Counter[str] = Counter()
        successful_counts: List[int] = []
        recent_run_latest_successful_counts: List[int] = []
        recent_ready_runs = 0
        recent_run_error_code_counts: Counter[str] = Counter()
        recent_run_abstain_reason_counts: Counter[str] = Counter()
        recent_run_provider_status_counts: Dict[str, Dict[str, int]] = defaultdict(dict)
        recent_healthy_provider_sets: Counter[str] = Counter()
        recent_primary_cause_counts: Counter[str] = Counter()
        latest_healthy_provider_set = "none"
        single_provider_only_runs = 0
        recent_run_readiness: List[bool] = []
        recent_run_single_provider_flags: List[bool] = []
        historical_runs_considered = 0
        historical_ready_runs = 0
        historical_run_error_code_counts: Counter[str] = Counter()
        historical_run_provider_status_counts: Dict[str, Dict[str, int]] = defaultdict(dict)
        historical_healthy_provider_sets: Counter[str] = Counter()
        historical_single_provider_only_runs = 0
        historical_xai_only_runs = 0
        historical_zero_healthy_provider_runs = 0
        consensus_ready_runs_observed = 0
        latest_consensus_ready_data_dir = ""
        latest_consensus_ready_run_timestamp = ""
        latest_consensus_ready_run_age_hours: Optional[float] = None

        required_consensus_models = max(1, int(getattr(self.config, "min_consensus_count", 2)))

        for payload in predictions:
            successful_counts.append(int(payload.get("successful_model_count", 0) or 0))
            abstain_reason = str(payload.get("abstain_reason", "") or "").strip()
            if abstain_reason:
                abstain_reasons[abstain_reason] += 1
            measurement_boundary = str(payload.get("measurement_boundary", "") or "").strip()
            if measurement_boundary:
                measurement_boundary_counts[measurement_boundary] += 1
            analysis_cohort = str(payload.get("analysis_cohort", "") or "").strip()
            if analysis_cohort:
                analysis_cohort_counts[analysis_cohort] += 1
            for item in payload.get("model_statuses", []) or []:
                if not isinstance(item, dict):
                    continue
                provider = str(item.get("provider", "unknown") or "unknown")
                status = str(item.get("status", "unknown") or "unknown")
                provider_status_counts.setdefault(provider, {})
                provider_status_counts[provider][status] = provider_status_counts[provider].get(status, 0) + 1
                error_code = str(item.get("error_code", "") or "").strip()
                if error_code:
                    error_code_counts[error_code] += 1

        for index, runtime_dir in enumerate(runtime_dirs):
            recent_run_audit = self._load_latest_run_audit(runtime_dir)
            recent_predictions = self._load_recent_predictions(runtime_dir, limit=10)
            recent_latest = recent_predictions[0] if recent_predictions else {}
            recent_scan_summary = self._build_latest_runtime_scan_summary(
                recent_run_audit.get("scanner_telemetry", {})
            )
            recent_primary_cause = self._classify_runtime_primary_cause(
                recent_scan_summary=recent_scan_summary,
                latest_prediction=recent_latest,
                latest_markets_found=int(recent_run_audit.get("markets_found", 0) or 0),
                latest_trades_executed=int(recent_run_audit.get("trades_executed", 0) or 0),
                required_consensus_models=required_consensus_models,
            )
            recent_primary_cause_counts[recent_primary_cause] += 1
            if not recent_predictions:
                continue
            recent_successful_count = int(recent_latest.get("successful_model_count", 0) or 0)
            recent_run_latest_successful_counts.append(recent_successful_count)
            is_ready_run = recent_successful_count >= required_consensus_models
            recent_run_readiness.append(is_ready_run)
            if is_ready_run:
                recent_ready_runs += 1
            recent_abstain_reason = str(recent_latest.get("abstain_reason", "") or "").strip()
            if recent_abstain_reason:
                recent_run_abstain_reason_counts[recent_abstain_reason] += 1
            healthy_providers: List[str] = []
            for item in recent_latest.get("model_statuses", []) or []:
                if not isinstance(item, dict):
                    continue
                provider = str(item.get("provider", "unknown") or "unknown")
                status = str(item.get("status", "unknown") or "unknown")
                if status == "ok":
                    healthy_providers.append(provider)
                recent_run_provider_status_counts.setdefault(provider, {})
                recent_run_provider_status_counts[provider][status] = (
                    recent_run_provider_status_counts[provider].get(status, 0) + 1
                )
                error_code = str(item.get("error_code", "") or "").strip()
                if error_code:
                    recent_run_error_code_counts[error_code] += 1
            healthy_key = "+".join(sorted(set(healthy_providers))) if healthy_providers else "none"
            recent_healthy_provider_sets[healthy_key] += 1
            if index == 0:
                latest_healthy_provider_set = healthy_key
            single_provider_control = len(set(healthy_providers)) == 1
            recent_run_single_provider_flags.append(single_provider_control)
            if single_provider_control:
                single_provider_only_runs += 1

        for runtime_dir in all_runtime_dirs:
            historical_predictions = self._load_recent_predictions(runtime_dir, limit=10)
            if not historical_predictions:
                continue
            historical_latest = historical_predictions[0]
            historical_runs_considered += 1
            historical_successful_count = int(historical_latest.get("successful_model_count", 0) or 0)
            historical_healthy_providers: List[str] = []
            for item in historical_latest.get("model_statuses", []) or []:
                if not isinstance(item, dict):
                    continue
                provider = str(item.get("provider", "unknown") or "unknown")
                status = str(item.get("status", "unknown") or "unknown")
                if status == "ok":
                    historical_healthy_providers.append(provider)
                historical_run_provider_status_counts.setdefault(provider, {})
                historical_run_provider_status_counts[provider][status] = (
                    historical_run_provider_status_counts[provider].get(status, 0) + 1
                )
                error_code = str(item.get("error_code", "") or "").strip()
                if error_code:
                    historical_run_error_code_counts[error_code] += 1
            historical_healthy_key = (
                "+".join(sorted(set(historical_healthy_providers)))
                if historical_healthy_providers
                else "none"
            )
            historical_healthy_provider_sets[historical_healthy_key] += 1
            if not historical_healthy_providers:
                historical_zero_healthy_provider_runs += 1
            elif len(set(historical_healthy_providers)) == 1:
                historical_single_provider_only_runs += 1
                if set(historical_healthy_providers) == {"xai"}:
                    historical_xai_only_runs += 1
            if historical_successful_count < required_consensus_models:
                continue
            historical_ready_runs += 1
            consensus_ready_runs_observed += 1
            if not latest_consensus_ready_data_dir:
                latest_consensus_ready_data_dir = str(runtime_dir)
                historical_run_audit = self._load_latest_run_audit(runtime_dir)
                latest_consensus_ready_run_timestamp = str(historical_run_audit.get("timestamp", "") or "")
                latest_consensus_ready_dt = self._parse_iso_datetime(latest_consensus_ready_run_timestamp)
                if latest_consensus_ready_dt is not None:
                    latest_consensus_ready_age_seconds = max(
                        0.0,
                        (datetime.now(timezone.utc) - latest_consensus_ready_dt).total_seconds(),
                    )
                    latest_consensus_ready_run_age_hours = round(latest_consensus_ready_age_seconds / 3600.0, 2)

        recent_runtime_blocked_streak_runs = 0
        for is_ready_run in recent_run_readiness:
            if is_ready_run:
                break
            recent_runtime_blocked_streak_runs += 1

        recent_single_provider_control_streak_runs = 0
        for single_provider_control in recent_run_single_provider_flags:
            if not single_provider_control:
                break
            recent_single_provider_control_streak_runs += 1

        latest_prediction = predictions[0] if predictions else {}
        latest_successful_count = int(latest_prediction.get("successful_model_count", 0) or 0)
        ready = latest_successful_count >= required_consensus_models
        phase_progress = run_audit.get("phase_progress", []) if isinstance(run_audit, dict) else []
        latest_run_timestamp = str(run_audit.get("timestamp", "") or "")
        latest_run_dt = self._parse_iso_datetime(latest_run_timestamp)
        latest_run_age_hours: Optional[float] = None
        runtime_freshness_verdict = "unknown"
        fresh_enough_for_runtime_summary = False
        if latest_run_dt is not None:
            latest_run_age_seconds = max(0.0, (datetime.now(timezone.utc) - latest_run_dt).total_seconds())
            latest_run_age_hours = round(latest_run_age_seconds / 3600.0, 2)
            fresh_enough_for_runtime_summary = latest_run_age_hours <= runtime_freshness_threshold_hours
            runtime_freshness_verdict = (
                "runtime_recent"
                if fresh_enough_for_runtime_summary
                else "runtime_stale"
            )
        latest_current_price = self._safe_float(latest_prediction.get("current_price"), 0.0)
        latest_sigma_ratio = self._safe_float(latest_prediction.get("sigma_ratio"), 0.0)
        recent_runtime_dirs_considered = len(runtime_dirs)
        recent_runs_considered = len(recent_run_latest_successful_counts)
        recent_provider_ok_rates: Dict[str, float] = {}
        persistently_healthy_providers: List[str] = []
        persistently_blocked_providers: List[str] = []
        intermittent_providers: List[str] = []
        for provider, status_counts in recent_run_provider_status_counts.items():
            ok_runs = int(status_counts.get("ok", 0) or 0)
            ok_rate = (ok_runs / recent_runs_considered) if recent_runs_considered > 0 else 0.0
            recent_provider_ok_rates[provider] = round(ok_rate, 3)
            if recent_runs_considered > 0 and ok_runs >= recent_runs_considered:
                persistently_healthy_providers.append(provider)
            elif ok_runs <= 0:
                persistently_blocked_providers.append(provider)
            else:
                intermittent_providers.append(provider)
        most_common_recent_healthy_provider_set = ""
        if recent_healthy_provider_sets:
            most_common_recent_healthy_provider_set = sorted(
                recent_healthy_provider_sets.items(),
                key=lambda item: (-item[1], item[0]),
            )[0][0]
        most_common_recent_primary_cause = ""
        if recent_primary_cause_counts:
            most_common_recent_primary_cause = sorted(
                recent_primary_cause_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[0][0]
        historical_provider_ok_rates: Dict[str, float] = {}
        for provider, status_counts in historical_run_provider_status_counts.items():
            ok_runs = int(status_counts.get("ok", 0) or 0)
            ok_rate = (ok_runs / historical_runs_considered) if historical_runs_considered > 0 else 0.0
            historical_provider_ok_rates[provider] = round(ok_rate, 3)
        most_common_historical_healthy_provider_set = ""
        if historical_healthy_provider_sets:
            most_common_historical_healthy_provider_set = sorted(
                historical_healthy_provider_sets.items(),
                key=lambda item: (-item[1], item[0]),
            )[0][0]
        historical_other_provider_mix_runs = max(
            0,
            historical_runs_considered - historical_xai_only_runs - historical_zero_healthy_provider_runs,
        )
        consensus_ready_history_verdict = (
            "consensus_ready_seen_in_history"
            if consensus_ready_runs_observed > 0
            else "no_consensus_ready_run_observed"
        )
        runtime_provider_verdict = self._build_runtime_provider_verdict(
            fresh_enough_for_runtime_summary=fresh_enough_for_runtime_summary,
            recent_runs_considered=recent_runs_considered,
            recent_ready_runs=recent_ready_runs,
            single_provider_only_rate=(
                round(single_provider_only_runs / recent_runs_considered, 3)
                if recent_runs_considered > 0
                else 0.0
            ),
            persistently_blocked_providers=sorted(persistently_blocked_providers),
            latest_abstain_reason=str(latest_prediction.get("abstain_reason", "") or ""),
            most_common_recent_healthy_provider_set=most_common_recent_healthy_provider_set,
        )
        latest_markets_found = int(run_audit.get("markets_found", 0) or 0)
        latest_trades_executed = int(run_audit.get("trades_executed", 0) or 0)
        latest_scanner_summary = self._build_latest_runtime_scan_summary(
            run_audit.get("scanner_telemetry", {})
        )
        latest_cycle_interpretation = self._build_latest_cycle_interpretation(
            fresh_enough_for_runtime_summary=fresh_enough_for_runtime_summary,
            latest_markets_found=latest_markets_found,
            latest_trades_executed=latest_trades_executed,
            latest_successful_model_count=latest_successful_count,
            required_consensus_models=required_consensus_models,
            latest_abstain_reason=str(latest_prediction.get("abstain_reason", "") or ""),
            latest_healthy_provider_set=latest_healthy_provider_set,
            runtime_provider_verdict=runtime_provider_verdict,
        )

        return {
            "ready": ready,
            "status": "ok" if ready else "degraded",
            "runtime_freshness_verdict": runtime_freshness_verdict,
            "latest_run_age_hours": latest_run_age_hours,
            "runtime_freshness_threshold_hours": runtime_freshness_threshold_hours,
            "fresh_enough_for_runtime_summary": fresh_enough_for_runtime_summary,
            "required_consensus_models": required_consensus_models,
            "latest_data_dir": str(latest_dir),
            "total_runtime_dirs_scanned": len(all_runtime_dirs),
            "recent_data_dirs": [str(path) for path in runtime_dirs],
            "latest_run_timestamp": latest_run_timestamp,
            "latest_run_status": str(run_audit.get("status", "")),
            "latest_cycle_duration_seconds": self._safe_float(run_audit.get("phase_progress", [{}])[-1].get("elapsed_seconds") if phase_progress else run_audit.get("duration_seconds"), 0.0),
            "latest_market_scan_seconds": self._phase_elapsed(phase_progress, "market_scan"),
            "latest_swarm_analysis_seconds": self._phase_elapsed(phase_progress, "swarm_analysis"),
            "latest_markets_found": latest_markets_found,
            "latest_trades_executed": latest_trades_executed,
            "latest_runtime_scan_summary": latest_scanner_summary,
            "latest_cycle_interpretation": latest_cycle_interpretation,
            "recent_prediction_count": len(predictions),
            "recent_runtime_dirs_considered": recent_runtime_dirs_considered,
            "recent_prediction_runs_considered": recent_runs_considered,
            "recent_runs_considered": recent_runs_considered,
            "recent_ready_runs": recent_ready_runs,
            "recent_degraded_runs": max(0, recent_runs_considered - recent_ready_runs),
            "recent_runtime_blocked_streak_runs": recent_runtime_blocked_streak_runs,
            "recent_single_provider_control_streak_runs": recent_single_provider_control_streak_runs,
            "consensus_ready_runs_observed": consensus_ready_runs_observed,
            "consensus_ready_history_verdict": consensus_ready_history_verdict,
            "latest_consensus_ready_data_dir": latest_consensus_ready_data_dir,
            "latest_consensus_ready_run_timestamp": latest_consensus_ready_run_timestamp,
            "latest_consensus_ready_run_age_hours": latest_consensus_ready_run_age_hours,
            "historical_runs_considered": historical_runs_considered,
            "historical_ready_runs": historical_ready_runs,
            "historical_degraded_runs": max(0, historical_runs_considered - historical_ready_runs),
            "historical_run_error_code_counts": dict(historical_run_error_code_counts),
            "historical_run_provider_status_counts": {
                provider: dict(status_counts)
                for provider, status_counts in historical_run_provider_status_counts.items()
            },
            "historical_provider_ok_rates": historical_provider_ok_rates,
            "historical_healthy_provider_sets": dict(historical_healthy_provider_sets),
            "historical_single_provider_only_runs": historical_single_provider_only_runs,
            "historical_single_provider_only_rate": (
                round(historical_single_provider_only_runs / historical_runs_considered, 3)
                if historical_runs_considered > 0
                else 0.0
            ),
            "historical_xai_only_runs": historical_xai_only_runs,
            "historical_xai_only_rate": (
                round(historical_xai_only_runs / historical_runs_considered, 3)
                if historical_runs_considered > 0
                else 0.0
            ),
            "historical_zero_healthy_provider_runs": historical_zero_healthy_provider_runs,
            "historical_zero_healthy_provider_rate": (
                round(historical_zero_healthy_provider_runs / historical_runs_considered, 3)
                if historical_runs_considered > 0
                else 0.0
            ),
            "historical_other_provider_mix_runs": historical_other_provider_mix_runs,
            "historical_other_provider_mix_rate": (
                round(historical_other_provider_mix_runs / historical_runs_considered, 3)
                if historical_runs_considered > 0
                else 0.0
            ),
            "most_common_historical_healthy_provider_set": most_common_historical_healthy_provider_set,
            "latest_successful_model_count": latest_successful_count,
            "recent_average_latest_successful_model_count": (
                round(sum(recent_run_latest_successful_counts) / len(recent_run_latest_successful_counts), 2)
                if recent_run_latest_successful_counts
                else 0.0
            ),
            "average_successful_model_count": round(sum(successful_counts) / len(successful_counts), 2) if successful_counts else 0.0,
            "latest_abstain_reason": str(latest_prediction.get("abstain_reason", "") or ""),
            "latest_measurement_boundary": str(latest_prediction.get("measurement_boundary", "") or ""),
            "latest_analysis_cohort": str(latest_prediction.get("analysis_cohort", "") or ""),
            "latest_current_price_present": latest_current_price > 0.0,
            "latest_current_price": round(latest_current_price, 4) if latest_current_price > 0.0 else None,
            "latest_sigma_ratio": round(latest_sigma_ratio, 4) if latest_sigma_ratio > 0.0 else None,
            "degraded_prediction_count": int(measurement_boundary_counts.get("degraded_swarm", 0)),
            "single_model_control_count": int(analysis_cohort_counts.get("single_model_control", 0)),
            "measurement_boundary_counts": dict(measurement_boundary_counts),
            "analysis_cohort_counts": dict(analysis_cohort_counts),
            "abstain_reason_counts": dict(abstain_reasons),
            "error_code_counts": dict(error_code_counts),
            "provider_status_counts": dict(provider_status_counts),
            "recent_run_abstain_reason_counts": dict(recent_run_abstain_reason_counts),
            "recent_run_error_code_counts": dict(recent_run_error_code_counts),
            "recent_run_provider_status_counts": dict(recent_run_provider_status_counts),
            "recent_provider_ok_rates": dict(recent_provider_ok_rates),
            "recent_healthy_provider_sets": dict(recent_healthy_provider_sets),
            "recent_primary_cause_counts": dict(recent_primary_cause_counts),
            "recent_primary_cause_counted_runs": int(sum(recent_primary_cause_counts.values())),
            "most_common_recent_primary_cause": most_common_recent_primary_cause,
            "latest_healthy_provider_set": latest_healthy_provider_set,
            "most_common_recent_healthy_provider_set": most_common_recent_healthy_provider_set,
            "runtime_provider_verdict": runtime_provider_verdict,
            "single_provider_only_runs": single_provider_only_runs,
            "single_provider_only_rate": (
                round(single_provider_only_runs / recent_runs_considered, 3)
                if recent_runs_considered > 0
                else 0.0
            ),
            "persistently_healthy_providers": sorted(persistently_healthy_providers),
            "persistently_blocked_providers": sorted(persistently_blocked_providers),
            "intermittent_providers": sorted(intermittent_providers),
        }

    @staticmethod
    def _build_latest_runtime_scan_summary(scanner_telemetry: Any) -> Dict[str, Any]:
        if not isinstance(scanner_telemetry, dict) or not scanner_telemetry:
            return {
                "status": "no_scanner_telemetry",
                "reason_codes": ["no_scanner_telemetry"],
                "query_count": 0,
                "raw_records": 0,
                "parsed": 0,
                "filtered": 0,
                "tradeable": 0,
                "no_markets": False,
                "top_exclusion_reasons": [],
            }

        exclusion_reasons = scanner_telemetry.get("exclusion_reasons", {})
        sorted_exclusions: List[Dict[str, Any]] = []
        if isinstance(exclusion_reasons, dict):
            sorted_exclusions = [
                {"key": str(key), "count": int(value or 0)}
                for key, value in sorted(
                    exclusion_reasons.items(),
                    key=lambda item: (-int(item[1] or 0), str(item[0])),
                )
                if int(value or 0) > 0
            ][:3]

        tradeable = int(scanner_telemetry.get("tradeable", 0) or 0)
        no_markets = bool(scanner_telemetry.get("no_markets", False))
        if tradeable <= 0 or no_markets:
            status = "NO_TRADEABLE_MARKETS_IN_LATEST_RUNTIME_SCAN"
            reason_codes = [item["key"] for item in sorted_exclusions] or ["no_tradeable_markets"]
        else:
            status = "TRADEABLE_MARKETS_FOUND_IN_LATEST_RUNTIME_SCAN"
            reason_codes = []

        return {
            "status": status,
            "reason_codes": reason_codes,
            "query_count": int(scanner_telemetry.get("query_count", 0) or 0),
            "raw_records": int(scanner_telemetry.get("raw_records", 0) or 0),
            "parsed": int(scanner_telemetry.get("parsed", 0) or 0),
            "filtered": int(scanner_telemetry.get("filtered", 0) or 0),
            "tradeable": tradeable,
            "no_markets": no_markets,
            "top_exclusion_reasons": sorted_exclusions,
        }

    @staticmethod
    def _classify_runtime_primary_cause(
        *,
        recent_scan_summary: Dict[str, Any],
        latest_prediction: Dict[str, Any],
        latest_markets_found: int,
        latest_trades_executed: int,
        required_consensus_models: int,
    ) -> str:
        if str(recent_scan_summary.get("status", "") or "") == "NO_TRADEABLE_MARKETS_IN_LATEST_RUNTIME_SCAN":
            return "inventory_blocked_no_tradeable_markets"
        if latest_trades_executed > 0:
            return "trade_executed"
        if not isinstance(latest_prediction, dict) or not latest_prediction:
            return "no_prediction_artifact"
        successful_model_count = int(latest_prediction.get("successful_model_count", 0) or 0)
        if successful_model_count >= max(1, int(required_consensus_models or 1)):
            return "consensus_ready"
        healthy_providers = {
            str(item.get("provider", "") or "")
            for item in (latest_prediction.get("model_statuses", []) or [])
            if isinstance(item, dict) and str(item.get("status", "") or "") == "ok"
        }
        if not healthy_providers:
            return "provider_blocked_no_healthy_provider"
        if len(healthy_providers) == 1:
            return "single_provider_control"
        if latest_markets_found > 0:
            return "degraded_swarm_with_markets"
        return "unknown_no_trade_cause"

    @staticmethod
    def _build_runtime_provider_verdict(
        *,
        fresh_enough_for_runtime_summary: bool,
        recent_runs_considered: int,
        recent_ready_runs: int,
        single_provider_only_rate: float,
        persistently_blocked_providers: List[str],
        latest_abstain_reason: str,
        most_common_recent_healthy_provider_set: str,
    ) -> Dict[str, Any]:
        if recent_runs_considered <= 0:
            return {
                "status": "NO_RUNTIME_EVIDENCE",
                "reason_codes": ["no_recent_runtime_runs"],
                "healthy_provider_set": "none",
            }

        reason_codes: List[str] = []
        if not fresh_enough_for_runtime_summary:
            reason_codes.append("runtime_evidence_stale")
        if recent_ready_runs <= 0:
            reason_codes.append("no_recent_consensus_ready_runs")
        if single_provider_only_rate >= 0.8:
            reason_codes.append("single_provider_control")
        if persistently_blocked_providers:
            reason_codes.append("persistently_blocked_providers")
        if latest_abstain_reason:
            reason_codes.append(latest_abstain_reason)

        if not fresh_enough_for_runtime_summary:
            status = "STALE_RUNTIME_EVIDENCE"
        elif recent_ready_runs <= 0:
            status = "CURRENTLY_BLOCKED"
        elif single_provider_only_rate >= 0.8:
            status = "SINGLE_PROVIDER_DEGRADED"
        else:
            status = "MIXED_RECENT_HEALTH"

        return {
            "status": status,
            "reason_codes": reason_codes,
            "healthy_provider_set": most_common_recent_healthy_provider_set or "none",
        }

    @staticmethod
    def _build_latest_cycle_interpretation(
        *,
        fresh_enough_for_runtime_summary: bool,
        latest_markets_found: int,
        latest_trades_executed: int,
        latest_successful_model_count: int,
        required_consensus_models: int,
        latest_abstain_reason: str,
        latest_healthy_provider_set: str,
        runtime_provider_verdict: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not fresh_enough_for_runtime_summary:
            return {
                "status": "STALE_RUNTIME_CYCLE",
                "reason_codes": ["runtime_evidence_stale"],
            }
        if latest_trades_executed > 0:
            return {
                "status": "TRADES_EXECUTED",
                "reason_codes": [],
            }
        if latest_markets_found <= 0:
            return {
                "status": "NO_MARKETS_FOUND",
                "reason_codes": ["no_tradeable_markets"],
            }
        provider_status = str(runtime_provider_verdict.get("status", "") or "")
        if provider_status == "CURRENTLY_BLOCKED":
            provider_reason_codes = [
                str(code or "")
                for code in (runtime_provider_verdict.get("reason_codes", []) or [])
                if str(code or "") and str(code or "") != "single_provider_control"
            ]
            if latest_healthy_provider_set == "none":
                provider_reason_codes.append("no_healthy_provider_current_run")
            elif latest_healthy_provider_set and "+" not in latest_healthy_provider_set:
                provider_reason_codes.append("single_provider_control_current_run")
            return {
                "status": "PROVIDER_BLOCKED_NO_TRADE",
                "reason_codes": [
                    "markets_found_but_provider_blocked",
                    *provider_reason_codes,
                ],
            }
        if latest_successful_model_count < required_consensus_models:
            return {
                "status": "DEGRADED_SWARM_NO_TRADE",
                "reason_codes": [
                    "markets_found_but_swarm_degraded",
                    latest_abstain_reason or "no_consensus",
                ],
            }
        return {
            "status": "HEALTHY_SWARM_NO_TRADE",
            "reason_codes": [latest_abstain_reason or "no_trade_signal"],
        }

    @staticmethod
    def _build_swarm_health(config: PolymarketCLIConfig) -> Dict[str, Any]:
        try:
            from src.models.model_factory import ModelFactory
        except Exception as exc:  # pragma: no cover - defensive
            return {
                "ready": False,
                "status": "model_factory_unavailable",
                "error": str(exc),
                "configured_models": [],
                "available_models": 0,
                "unavailable_models": len(getattr(config, "swarm_models", []) or []),
            }

        factory = ModelFactory()
        api_key_map = {}
        try:
            api_key_map = factory._get_api_key_mapping()  # type: ignore[attr-defined]
        except Exception:
            api_key_map = {}

        configured_models: List[Dict[str, Any]] = []
        for provider, model_name in getattr(config, "swarm_models", []) or []:
            provider_key = api_key_map.get(provider, "")
            try:
                provider_available = bool(factory.is_model_available(provider))
            except Exception:
                provider_available = False

            if not provider_available:
                status = "provider_unavailable"
            else:
                try:
                    model = factory.get_model(provider, model_name)
                except Exception:
                    model = None
                status = "ok" if model is not None else "model_name_unavailable"

            configured_models.append(
                {
                    "provider": provider,
                    "model_name": model_name,
                    "status": status,
                    "api_key_env": provider_key,
                    "api_key_present": bool(os.getenv(provider_key)) if provider_key else None,
                }
            )

        available_count = sum(1 for item in configured_models if item.get("status") == "ok")
        unavailable_count = len(configured_models) - available_count
        ready = available_count >= max(1, int(getattr(config, "min_consensus_count", 2)))
        return {
            "ready": ready,
            "status": "ok" if ready else "degraded",
            "required_consensus_models": int(getattr(config, "min_consensus_count", 2)),
            "available_models": available_count,
            "unavailable_models": unavailable_count,
            "configured_models": configured_models,
        }

    def _build_experiment_matrix(self, base: ParamSet) -> Dict[str, Any]:
        candidates: List[Dict[str, Any]] = []
        symbol_sets = [
            (["ETH"], "ETH"),
            (["BTC"], "BTC"),
            (["ETH", "BTC"], "ETH_BTC"),
        ]
        source_modes = [
            (True, False, "swarm_only"),
            (False, True, "arb_only"),
            (True, True, "swarm_arb"),
        ]
        min_expiry_options = [base.min_expiry_hours, 0.0, 1.0, 4.0]
        max_expiry_options = [1.0, 4.0, 12.0, 24.0, None]
        seen: set[str] = set()

        for symbols, symbol_label in symbol_sets:
            for allow_swarm, allow_arb, source_label in source_modes:
                for min_expiry in min_expiry_options:
                    for max_expiry in max_expiry_options:
                        if min_expiry is not None and max_expiry is not None and float(min_expiry) > float(max_expiry):
                            continue
                        params = replace(
                            base,
                            allowed_symbols=list(symbols),
                            allow_swarm=allow_swarm,
                            allow_arb=allow_arb,
                            min_expiry_hours=min_expiry,
                            max_expiry_hours=max_expiry,
                        )
                        key = json.dumps(asdict(params), sort_keys=True, default=str)
                        if key in seen:
                            continue
                        seen.add(key)
                        result = self.scorer.score(params)
                        replay = self.scorer.score_replay(params)
                        candidates.append(
                            {
                                "label": (
                                    f"{symbol_label}:{source_label}:"
                                    f"min={min_expiry if min_expiry is not None else 'none'}:"
                                    f"max={max_expiry if max_expiry is not None else 'none'}"
                                ),
                                "params": asdict(params),
                                "score": round(float(result.score), 2),
                                "total_pnl": round(float(result.total_pnl), 2),
                                "roi": round(float(result.roi), 3),
                                "win_rate": round(float(result.win_rate), 3),
                                "filtered_trades": int(result.filtered_trades),
                                "replay_accepted": bool(replay.accepted),
                                "holdout_score": round(float(replay.holdout.score), 2),
                                "holdout_trades": int(replay.holdout.filtered_trades),
                            }
                        )

        ranked = sorted(
            candidates,
            key=lambda item: (
                item["replay_accepted"],
                item["score"],
                item["total_pnl"],
                item["filtered_trades"],
            ),
            reverse=True,
        )
        positive_candidates = [
                item
                for item in ranked
                if float(item["total_pnl"]) > 0.0 and int(item["filtered_trades"]) >= MIN_RESEARCH_CANDIDATE_TRADES
            ]
        low_sample_candidates = [
            item
            for item in ranked
            if float(item["total_pnl"]) > 0.0 and 0 < int(item["filtered_trades"]) < MIN_RESEARCH_CANDIDATE_TRADES
        ]
        return {
            "best_candidate": positive_candidates[0] if positive_candidates else {},
            "best_low_sample_candidate": low_sample_candidates[0] if low_sample_candidates else {},
            "top_candidates": ranked[:10],
            "positive_candidates": positive_candidates[:10],
            "low_sample_candidates": low_sample_candidates[:10],
            "expiry_policy_snapshot": self._build_expiry_policy_snapshot(candidates, base),
            "btc_positive_any": any(
                item["params"].get("allowed_symbols") == ["BTC"] and float(item["total_pnl"]) > 0.0
                for item in ranked
            ),
        }

    def _build_expiry_policy_snapshot(self, candidates: List[Dict[str, Any]], base: ParamSet) -> Dict[str, Any]:
        eth_candidates = [
            item
            for item in candidates
            if isinstance(item, dict) and item.get("params", {}).get("allowed_symbols") == ["ETH"]
        ]
        active_profile_candidates = [
            item
            for item in eth_candidates
            if item.get("params", {}).get("allow_swarm") == base.allow_swarm
            and item.get("params", {}).get("allow_arb") == base.allow_arb
            and item.get("params", {}).get("min_expiry_hours") == base.min_expiry_hours
        ]
        if not eth_candidates:
            return {
                "scope": "ETH-only",
                "comparison_basis": {},
                "current_cap": {},
                "best_active_profile_cap": {},
                "best_active_profile_cap_with_min_sample": {},
                "best_exploratory_cap_any_profile": {},
                "best_active_profile_cap_delta_vs_current": {},
                "best_active_profile_cap_with_min_sample_delta_vs_current": {},
                "rows": [],
                "positive_active_profile_caps_with_min_sample": [],
                "positive_active_profile_caps_low_sample": [],
            }

        by_cap: Dict[Any, Dict[str, Any]] = {}
        for item in active_profile_candidates:
            cap = item.get("params", {}).get("max_expiry_hours")
            previous = by_cap.get(cap)
            if previous is None or self._candidate_rank_key(item) > self._candidate_rank_key(previous):
                by_cap[cap] = item

        ordered_caps = sorted(
            by_cap.keys(),
            key=lambda value: (value is None, float(value) if value is not None else float("inf")),
        )
        rows: List[Dict[str, Any]] = []
        for cap in ordered_caps:
            item = by_cap[cap]
            rows.append(
                {
                    "cap_label": self._format_expiry_cap_label(cap),
                    "max_expiry_hours": cap,
                    "label": item.get("label", "unknown"),
                    "score": float(item.get("score", 0.0) or 0.0),
                    "total_pnl": float(item.get("total_pnl", 0.0) or 0.0),
                    "filtered_trades": int(item.get("filtered_trades", 0) or 0),
                    "replay_accepted": bool(item.get("replay_accepted", False)),
                    "holdout_trades": int(item.get("holdout_trades", 0) or 0),
                }
            )

        current_item = by_cap.get(base.max_expiry_hours)
        best_active_profile_item = max(by_cap.values(), key=self._candidate_rank_key) if by_cap else None
        active_profile_candidates_with_min_sample = [
            item
            for item in by_cap.values()
            if int(item.get("filtered_trades", 0) or 0) >= MIN_RESEARCH_CANDIDATE_TRADES
        ]
        best_active_profile_item_with_min_sample = (
            max(active_profile_candidates_with_min_sample, key=self._candidate_rank_key)
            if active_profile_candidates_with_min_sample
            else None
        )
        best_exploratory_item = max(eth_candidates, key=self._candidate_rank_key)
        positive_active_profile_caps_with_min_sample = [
            row["cap_label"]
            for row in rows
            if float(row.get("total_pnl", 0.0)) > 0.0
            and int(row.get("filtered_trades", 0) or 0) >= MIN_RESEARCH_CANDIDATE_TRADES
        ]
        positive_active_profile_caps_low_sample = [
            row["cap_label"]
            for row in rows
            if float(row.get("total_pnl", 0.0)) > 0.0
            and 0 < int(row.get("filtered_trades", 0) or 0) < MIN_RESEARCH_CANDIDATE_TRADES
        ]
        return {
            "scope": "ETH-only",
            "comparison_basis": {
                "allow_swarm": base.allow_swarm,
                "allow_arb": base.allow_arb,
                "min_expiry_hours": base.min_expiry_hours,
                "profile_label": self._format_source_profile_label(base.allow_swarm, base.allow_arb, base.min_expiry_hours),
            },
            "current_cap": {
                "cap_label": self._format_expiry_cap_label(base.max_expiry_hours),
                "max_expiry_hours": base.max_expiry_hours,
                "label": current_item.get("label", "unknown") if current_item else "unknown",
                "score": float(current_item.get("score", 0.0) or 0.0) if current_item else 0.0,
                "total_pnl": float(current_item.get("total_pnl", 0.0) or 0.0) if current_item else 0.0,
                "filtered_trades": int(current_item.get("filtered_trades", 0) or 0) if current_item else 0,
                "replay_accepted": bool(current_item.get("replay_accepted", False)) if current_item else False,
                "holdout_trades": int(current_item.get("holdout_trades", 0) or 0) if current_item else 0,
            },
            "best_active_profile_cap": {
                "cap_label": self._format_expiry_cap_label(best_active_profile_item.get("params", {}).get("max_expiry_hours")) if best_active_profile_item else self._format_expiry_cap_label(base.max_expiry_hours),
                "max_expiry_hours": best_active_profile_item.get("params", {}).get("max_expiry_hours") if best_active_profile_item else base.max_expiry_hours,
                "label": best_active_profile_item.get("label", "unknown") if best_active_profile_item else "unknown",
                "score": float(best_active_profile_item.get("score", 0.0) or 0.0) if best_active_profile_item else 0.0,
                "total_pnl": float(best_active_profile_item.get("total_pnl", 0.0) or 0.0) if best_active_profile_item else 0.0,
                "filtered_trades": int(best_active_profile_item.get("filtered_trades", 0) or 0) if best_active_profile_item else 0,
                "replay_accepted": bool(best_active_profile_item.get("replay_accepted", False)) if best_active_profile_item else False,
                "holdout_trades": int(best_active_profile_item.get("holdout_trades", 0) or 0) if best_active_profile_item else 0,
            },
            "best_active_profile_cap_with_min_sample": {
                "cap_label": self._format_expiry_cap_label(best_active_profile_item_with_min_sample.get("params", {}).get("max_expiry_hours")) if best_active_profile_item_with_min_sample else "none",
                "max_expiry_hours": best_active_profile_item_with_min_sample.get("params", {}).get("max_expiry_hours") if best_active_profile_item_with_min_sample else None,
                "label": best_active_profile_item_with_min_sample.get("label", "unknown") if best_active_profile_item_with_min_sample else "unknown",
                "score": float(best_active_profile_item_with_min_sample.get("score", 0.0) or 0.0) if best_active_profile_item_with_min_sample else 0.0,
                "total_pnl": float(best_active_profile_item_with_min_sample.get("total_pnl", 0.0) or 0.0) if best_active_profile_item_with_min_sample else 0.0,
                "filtered_trades": int(best_active_profile_item_with_min_sample.get("filtered_trades", 0) or 0) if best_active_profile_item_with_min_sample else 0,
                "replay_accepted": bool(best_active_profile_item_with_min_sample.get("replay_accepted", False)) if best_active_profile_item_with_min_sample else False,
                "holdout_trades": int(best_active_profile_item_with_min_sample.get("holdout_trades", 0) or 0) if best_active_profile_item_with_min_sample else 0,
            },
            "best_exploratory_cap_any_profile": {
                "cap_label": self._format_expiry_cap_label(best_exploratory_item.get("params", {}).get("max_expiry_hours")),
                "max_expiry_hours": best_exploratory_item.get("params", {}).get("max_expiry_hours"),
                "label": best_exploratory_item.get("label", "unknown"),
                "score": float(best_exploratory_item.get("score", 0.0) or 0.0),
                "total_pnl": float(best_exploratory_item.get("total_pnl", 0.0) or 0.0),
                "filtered_trades": int(best_exploratory_item.get("filtered_trades", 0) or 0),
                "replay_accepted": bool(best_exploratory_item.get("replay_accepted", False)),
                "holdout_trades": int(best_exploratory_item.get("holdout_trades", 0) or 0),
            },
            "best_active_profile_cap_delta_vs_current": self._build_expiry_delta(current_item, best_active_profile_item),
            "best_active_profile_cap_with_min_sample_delta_vs_current": self._build_expiry_delta(
                current_item,
                best_active_profile_item_with_min_sample,
            ),
            "active_profile_cap_verdict": self._build_expiry_policy_verdict(
                current_item=current_item,
                best_active_profile_item=best_active_profile_item,
                best_active_profile_item_with_min_sample=best_active_profile_item_with_min_sample,
                positive_active_profile_caps_with_min_sample=positive_active_profile_caps_with_min_sample,
                positive_active_profile_caps_low_sample=positive_active_profile_caps_low_sample,
            ),
            "rows": rows,
            "positive_active_profile_caps_with_min_sample": positive_active_profile_caps_with_min_sample,
            "positive_active_profile_caps_low_sample": positive_active_profile_caps_low_sample,
        }

    @staticmethod
    def _candidate_rank_key(item: Dict[str, Any]) -> tuple:
        params = item.get("params", {}) if isinstance(item, dict) else {}
        max_expiry_hours = params.get("max_expiry_hours")
        cap_tiebreak = float("-inf") if max_expiry_hours is None else -float(max_expiry_hours)
        return (
            bool(item.get("replay_accepted", False)),
            float(item.get("score", 0.0) or 0.0),
            float(item.get("total_pnl", 0.0) or 0.0),
            int(item.get("filtered_trades", 0) or 0),
            cap_tiebreak,
        )

    @staticmethod
    def _format_source_profile_label(allow_swarm: Any, allow_arb: Any, min_expiry_hours: Any) -> str:
        if allow_swarm and allow_arb:
            source_label = "swarm_arb"
        elif allow_swarm:
            source_label = "swarm_only"
        elif allow_arb:
            source_label = "arb_only"
        else:
            source_label = "disabled"
        min_label = "none" if min_expiry_hours is None else f"{float(min_expiry_hours):g}h"
        return f"{source_label} min={min_label}"

    @staticmethod
    def _build_expiry_delta(current_item: Optional[Dict[str, Any]], target_item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(current_item, dict) or not isinstance(target_item, dict) or not target_item:
            return {}
        current_pnl = float(current_item.get("total_pnl", 0.0) or 0.0)
        current_trades = int(current_item.get("filtered_trades", 0) or 0)
        current_score = float(current_item.get("score", 0.0) or 0.0)
        target_pnl = float(target_item.get("total_pnl", 0.0) or 0.0)
        target_trades = int(target_item.get("filtered_trades", 0) or 0)
        target_score = float(target_item.get("score", 0.0) or 0.0)
        return {
            "pnl_delta": round(target_pnl - current_pnl, 2),
            "filtered_trade_delta": target_trades - current_trades,
            "score_delta": round(target_score - current_score, 2),
        }

    def _build_expiry_policy_verdict(
        self,
        *,
        current_item: Optional[Dict[str, Any]],
        best_active_profile_item: Optional[Dict[str, Any]],
        best_active_profile_item_with_min_sample: Optional[Dict[str, Any]],
        positive_active_profile_caps_with_min_sample: List[str],
        positive_active_profile_caps_low_sample: List[str],
    ) -> Dict[str, Any]:
        verdict = {
            "status": "NO_PROMOTABLE_CAP",
            "reason_codes": [],
            "promotable_cap_label": "none",
            "sampled_research_cap_label": "none",
            "exploratory_cap_label": "none",
            "sampled_research_cap_improves_current": False,
        }
        reasons: List[str] = []

        current_pnl = float(current_item.get("total_pnl", 0.0) or 0.0) if isinstance(current_item, dict) else 0.0
        sampled_cap_label = "none"
        exploratory_cap_label = "none"
        sampled_research_cap_improves_current = False

        if positive_active_profile_caps_with_min_sample:
            promotable = positive_active_profile_caps_with_min_sample[0]
            verdict["status"] = "PROMOTABLE_WITH_SAMPLE"
            verdict["promotable_cap_label"] = promotable
        else:
            reasons.append("no_positive_cap_with_min_sample")

        if isinstance(best_active_profile_item_with_min_sample, dict) and best_active_profile_item_with_min_sample:
            sampled_cap_label = self._format_expiry_cap_label(
                best_active_profile_item_with_min_sample.get("params", {}).get("max_expiry_hours")
                if "params" in best_active_profile_item_with_min_sample
                else best_active_profile_item_with_min_sample.get("max_expiry_hours")
            )
            sampled_research_cap_improves_current = (
                float(best_active_profile_item_with_min_sample.get("total_pnl", 0.0) or 0.0) > current_pnl
            )
            if float(best_active_profile_item_with_min_sample.get("total_pnl", 0.0) or 0.0) < 0.0:
                reasons.append("best_sampled_cap_still_negative")
            if sampled_research_cap_improves_current:
                reasons.append("best_sampled_cap_improves_but_not_profitable")
        else:
            reasons.append("no_cap_with_min_sample")

        if positive_active_profile_caps_low_sample:
            exploratory_cap_label = positive_active_profile_caps_low_sample[0]
            reasons.append("only_low_sample_positive_cap")

        verdict["reason_codes"] = reasons
        verdict["sampled_research_cap_label"] = sampled_cap_label
        verdict["exploratory_cap_label"] = exploratory_cap_label
        verdict["sampled_research_cap_improves_current"] = sampled_research_cap_improves_current
        return verdict

    @staticmethod
    def _select_best_variant(scored: Dict[str, Any], require_accepted: bool = False) -> str:
        eligible = []
        for label, payload in scored.items():
            score = payload.get("score", {})
            replay = payload.get("replay", {})
            if int(score.get("filtered_trades", 0) or 0) <= 0:
                continue
            if require_accepted and not bool(replay.get("accepted", False)):
                continue
            eligible.append((label, payload))
        if not eligible:
            return ""
        return max(
            eligible,
            key=lambda item: (
                float(item[1]["score"].get("score", 0.0)),
                float(item[1]["score"].get("total_pnl", 0.0)),
                int(item[1]["score"].get("filtered_trades", 0) or 0),
            ),
        )[0]

    def _latest_runtime_data_dir(self) -> Optional[Path]:
        runtime_dirs = self._runtime_data_dirs_sorted(limit=1)
        return runtime_dirs[0] if runtime_dirs else None

    @staticmethod
    def _looks_like_runtime_data_dir(path: Path) -> bool:
        return (path / "run_audit.jsonl").exists() or (path / "predictions").is_dir()

    def _runtime_data_dirs_sorted(self, limit: Optional[int] = None) -> List[Path]:
        candidates: List[Path] = []
        base_dir = self.config.data_dir.parent
        if base_dir.exists():
            for child in base_dir.iterdir():
                if child.is_dir() and child.name.startswith("polymarket_trader"):
                    candidates.append(child)
        for item in self.active_data_dirs + self.data_dirs:
            path = Path(item)
            if path.exists() and path.is_dir():
                candidates.append(path)

        stamped: List[tuple[datetime, str, Path]] = []
        seen: set[str] = set()
        for path in candidates:
            if not self._looks_like_runtime_data_dir(path):
                continue
            key = str(path.resolve()) if path.exists() else str(path)
            if key in seen:
                continue
            seen.add(key)
            payload = self._load_latest_run_audit(path)
            timestamp = self._parse_iso_datetime(payload.get("timestamp")) if payload else None
            if timestamp is None and path.exists():
                timestamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if timestamp is None:
                continue
            stamped.append((timestamp, str(path), path))
        stamped.sort(key=lambda item: (item[0], item[1]), reverse=True)
        paths = [item[2] for item in stamped]
        return paths[:limit] if limit is not None else paths

    @staticmethod
    def _load_latest_run_audit(data_dir: Path) -> Dict[str, Any]:
        run_audit_path = data_dir / "run_audit.jsonl"
        if not run_audit_path.exists():
            return {}
        try:
            lines = [line.strip() for line in run_audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except OSError:
            return {}
        if not lines:
            return {}
        try:
            payload = json.loads(lines[-1])
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _load_recent_predictions(data_dir: Path, limit: int = 10) -> List[Dict[str, Any]]:
        pred_dir = data_dir / "predictions"
        if not pred_dir.exists():
            return []
        payloads: List[Dict[str, Any]] = []
        try:
            files = sorted(pred_dir.glob("prediction_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            return []
        for path in files[:limit]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                payloads.append(payload)
        return payloads

    @staticmethod
    def _phase_elapsed(phase_progress: List[Dict[str, Any]], phase: str) -> float:
        for item in reversed(phase_progress or []):
            if str(item.get("phase", "")) == phase and str(item.get("status", "")) == "completed":
                return QuantResearchTeam._safe_float(item.get("elapsed_seconds"), 0.0)
        return 0.0

    @staticmethod
    def _parse_iso_datetime(value: Any) -> Optional[datetime]:
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    @staticmethod
    def _scan_markets_with_timeout(scanner: CLIMarketScanner, timeout_seconds: int) -> List[CLIMarket]:
        result: Dict[str, Any] = {}
        error: Dict[str, BaseException] = {}

        def _worker() -> None:
            try:
                result["markets"] = scanner.scan_markets(force_refresh=True)
            except BaseException as exc:  # pragma: no cover - defensive
                error["exc"] = exc

        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()
        worker.join(timeout_seconds)
        if worker.is_alive():
            telemetry = dict(getattr(scanner, "last_scan_telemetry", {}) or {})
            telemetry["timeout"] = True
            telemetry["timeout_seconds"] = timeout_seconds
            scanner.last_scan_telemetry = telemetry
            cprint(
                f"Inventory scan timed out after {timeout_seconds}s; writing partial telemetry only",
                "yellow",
            )
            return []

        if error:
            raise error["exc"]
        return list(result.get("markets") or [])

    @staticmethod
    def _write_json(path: Path, payload: Dict[str, Any]) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    def _write_markdown(self, path: Path, report: Dict[str, Any]) -> None:
        edge = report.get("edge_snapshot", {})
        perf = report.get("performance_summary", {})
        replay = perf.get("replay", {}) if isinstance(perf, dict) else {}
        replay_diag = replay.get("cohort_diagnostics", {}) if isinstance(replay, dict) else {}
        holdout_probe = replay.get("trailing_holdout_probe", {}) if isinstance(replay, dict) else {}
        active_diag = replay_diag.get("all", {}) if isinstance(replay_diag, dict) else {}
        holdout_diag = replay_diag.get("holdout", {}) if isinstance(replay_diag, dict) else {}
        calibration_snapshot = report.get("calibration_snapshot", {})
        edge_quality_snapshot = report.get("edge_quality_snapshot", {})
        edge_timeframe_snapshot = report.get("edge_timeframe_snapshot", {})
        market_archetype_snapshot = report.get("market_archetype_snapshot", {})
        entry_price_snapshot = report.get("entry_price_snapshot", {})
        direction_snapshot = report.get("direction_snapshot", {})
        policy_rescue_snapshot = report.get("policy_rescue_snapshot", {})
        risk_return = report.get("risk_return_snapshot", {})
        expiry_policy = report.get("expiry_policy_snapshot", {})
        swarm_health = report.get("swarm_health", {})
        runtime_swarm_health = report.get("runtime_swarm_health", {})
        inventory = report.get("inventory_snapshot", {})
        inventory_diagnostics = report.get("inventory_diagnostics", {})
        blockers = report.get("blockers", [])
        deployment_verdict = report.get("deployment_verdict", {})
        symbol_verdicts = report.get("symbol_verdicts", {})
        surviving_patch_snapshot = report.get("surviving_patch_snapshot", {})
        active_edge_snapshot = report.get("active_edge_snapshot", {})
        runtime_regime_snapshot = report.get("runtime_regime_snapshot", {})
        priorities = report.get("priorities", [])
        manifest = report.get("team_manifest", {})
        timeframe_snapshot = self._summarize_timeframe_pnl(perf)

        lines = [
            "# Polymarket Quant Research Team",
            "",
            f"Generated: {report.get('generated_at', '')}",
            "",
            "## Current Edge",
            "",
        ]

        edge_summary = edge.get("summary", {})
        lines.extend([
            f"- Shipping verdict variant: `{edge_summary.get('best_variant_by_score', 'unknown')}`",
            f"- Best exploratory active-cohort variant: `{edge_summary.get('best_exploratory_variant_by_score', 'unknown')}`",
            f"- Best active configuration: `{self._format_active_edge_configuration(active_edge_snapshot.get('best_active_configuration', {}))}`",
            f"- Positive active configurations: `{int(active_edge_snapshot.get('positive_active_configuration_count', 0) or 0)}`",
            f"- Best positive active configuration: `{self._format_active_edge_configuration(active_edge_snapshot.get('best_positive_active_configuration', {}))}`",
            f"- Replay-accepted active configurations: `{int(active_edge_snapshot.get('replay_accepted_active_configuration_count', 0) or 0)}`",
            f"- Supported symbols today: `{', '.join(edge_summary.get('supported_symbols', [])) or 'none'}`",
            f"- ETH vs BTC PnL delta: `{edge_summary.get('eth_vs_btc_pnl_delta', 0.0):+.2f}`",
            f"- ETH+BTC expansion penalty: `{edge_summary.get('eth_btc_expansion_penalty', 0.0):+.2f}`",
            f"- Any replay gate accepted: `{edge_summary.get('replay_acceptance_any', False)}`",
            f"- Current runtime blocker: `{self._format_current_runtime_blocker(runtime_swarm_health)}`",
            f"- Runtime blocker regime: `{self._format_runtime_regime_snapshot(runtime_regime_snapshot)}`",
            f"- Active edge read: `{self._format_active_edge_snapshot(active_edge_snapshot)}`",
            f"- Surviving ETH patch: `{self._format_entry_price_row(surviving_patch_snapshot.get('patch', {}))}`",
            f"- Surviving ETH patch stress test: `{self._format_patch_concentration_row(surviving_patch_snapshot.get('concentration', {}))}`",
            f"- Surviving ETH patch verdict: `{self._format_confidence_gate_verdict(entry_price_snapshot.get('best_low_sample_independence_verdict', {}))}`",
            f"- Surviving ETH patch promotability: `{self._format_surviving_patch_promotability(surviving_patch_snapshot.get('promotability', {}))}`",
            "",
            "## Deployment Verdict",
            "",
            f"- Status: `{deployment_verdict.get('status', 'UNKNOWN')}`",
            f"- Deployable now: `{deployment_verdict.get('deployable_now', False)}`",
            f"- Current scope: `{deployment_verdict.get('current_scope', 'unknown')}`",
            f"- Deployment target: `{deployment_verdict.get('deployment_target', 'unknown')}`",
            f"- Approved symbols: `{', '.join(deployment_verdict.get('approved_symbols', [])) or 'none'}`",
            f"- BTC allowed: `{deployment_verdict.get('btc_allowed', False)}`",
            f"- Arbitrage policy: `{deployment_verdict.get('arbitrage_policy', 'unknown')}`",
            f"- Verdict reason codes: `{deployment_verdict.get('reason_codes', [])}`",
            "",
            "## Symbol Verdicts",
            "",
        ])

        for symbol in ("ETH", "BTC"):
            symbol_report = symbol_verdicts.get(symbol, {}) if isinstance(symbol_verdicts, dict) else {}
            lines.extend([
                f"- {symbol}: `{symbol_report.get('status', 'UNKNOWN')}` / `{symbol_report.get('edge_status', 'unknown')}`",
                f"- {symbol} current lane: `{self._format_symbol_lane(symbol_report.get('current_lane', {}))}`",
                f"- {symbol} best measured positive lane: `{self._format_symbol_lane(symbol_report.get('best_measured_positive_lane', {}))}`",
                f"- {symbol} best low-sample positive lane: `{self._format_symbol_lane(symbol_report.get('best_low_sample_positive_lane', {}))}`",
                f"- {symbol} reason codes: `{symbol_report.get('reason_codes', [])}`",
            ])
        lines.extend([
            "",
            "## Best Measured Candidate",
            "",
        ])

        requirements = deployment_verdict.get("requirements", [])
        if requirements:
            lines.extend([
                "## Deployment Requirements",
                "",
            ])
            for item in requirements:
                lines.append(f"- {item}")
            lines.append("")

        best_candidate = edge_summary.get("best_research_candidate") or {}
        low_sample_candidate = edge_summary.get("best_low_sample_candidate") or {}
        if best_candidate:
            lines.extend([
                f"- Candidate: `{best_candidate.get('label', 'unknown')}`",
                f"- Score: `{float(best_candidate.get('score', 0.0)):.2f}`",
                f"- PnL: `${float(best_candidate.get('total_pnl', 0.0)):+.2f}`",
                f"- Trades: `{int(best_candidate.get('filtered_trades', 0))}`",
                f"- Replay accepted: `{best_candidate.get('replay_accepted', False)}`",
                "",
            ])
        else:
            lines.extend([
                f"- Candidate: `none with >= {MIN_RESEARCH_CANDIDATE_TRADES} filtered trades`",
                (
                    f"- Best low-sample lead: `{low_sample_candidate.get('label', 'none')}` "
                    f"({int(low_sample_candidate.get('filtered_trades', 0))} trades, "
                    f"PnL `${float(low_sample_candidate.get('total_pnl', 0.0)):+.2f}`)"
                    if low_sample_candidate
                    else "- Best low-sample lead: `none`"
                ),
                f"- Best low-sample lead verdict: `{self._format_confidence_gate_verdict(entry_price_snapshot.get('best_low_sample_independence_verdict', {}))}`",
                "",
            ])
        lines.extend([
            "## Expiry Policy",
            "",
            f"- Scope: `{expiry_policy.get('scope', 'ETH-only')}`",
            f"- Active ETH profile basis: `{expiry_policy.get('comparison_basis', {}).get('profile_label', 'unknown')}`",
            f"- Current ETH cap on active profile: `{self._format_expiry_policy_row(expiry_policy.get('current_cap', {}))}`",
            f"- Best active-profile ETH cap: `{self._format_expiry_policy_row(expiry_policy.get('best_active_profile_cap', {}))}`",
            f"- Best active-profile cap delta vs current: `{self._format_expiry_policy_delta(expiry_policy.get('best_active_profile_cap_delta_vs_current', {}))}`",
            f"- Best active-profile ETH cap with >= {MIN_RESEARCH_CANDIDATE_TRADES} trades: `{self._format_expiry_policy_row(expiry_policy.get('best_active_profile_cap_with_min_sample', {}))}`",
            f"- Best sampled active-profile cap delta vs current: `{self._format_expiry_policy_delta(expiry_policy.get('best_active_profile_cap_with_min_sample_delta_vs_current', {}))}`",
            f"- Best exploratory ETH cap across any profile: `{self._format_expiry_policy_row(expiry_policy.get('best_exploratory_cap_any_profile', {}))}`",
            f"- Active-profile cap verdict: `{self._format_expiry_policy_verdict(expiry_policy.get('active_profile_cap_verdict', {}))}`",
            f"- Positive active-profile caps with >= {MIN_RESEARCH_CANDIDATE_TRADES} trades: `{', '.join(expiry_policy.get('positive_active_profile_caps_with_min_sample', [])) or 'none'}`",
            f"- Positive active-profile low-sample caps: `{', '.join(expiry_policy.get('positive_active_profile_caps_low_sample', [])) or 'none'}`",
            f"- Active-profile ETH cap sweep: `{self._format_expiry_policy_rows(expiry_policy.get('rows', []))}`",
            "",
        ])
        lines.extend([
            "## Swarm Health",
            "",
            f"- Ready for live paper analysis: `{swarm_health.get('ready', False)}`",
            f"- Available configured models: `{swarm_health.get('available_models', 0)}`",
            f"- Unavailable configured models: `{swarm_health.get('unavailable_models', 0)}`",
            "",
            "## Runtime Swarm Health",
            "",
            f"- Latest runtime data dir: `{runtime_swarm_health.get('latest_data_dir', '') or 'none'}`",
            f"- Runtime ready: `{runtime_swarm_health.get('ready', False)}`",
            f"- Runtime freshness verdict: `{runtime_swarm_health.get('runtime_freshness_verdict', 'unknown')}`",
            f"- Latest run age hours: `{self._format_optional_hours(runtime_swarm_health.get('latest_run_age_hours'))}`",
            f"- Runtime freshness threshold hours: `{self._format_optional_hours(runtime_swarm_health.get('runtime_freshness_threshold_hours'))}`",
            f"- Runtime fresh enough for summary: `{runtime_swarm_health.get('fresh_enough_for_runtime_summary', False)}`",
            f"- Recent runtime dirs / prediction-bearing runs: `{runtime_swarm_health.get('recent_runtime_dirs_considered', 0)}` / `{runtime_swarm_health.get('recent_prediction_runs_considered', 0)}`",
            f"- Runtime provider verdict: `{self._format_runtime_provider_verdict(runtime_swarm_health.get('runtime_provider_verdict', {}))}`",
            f"- Latest cycle interpretation: `{self._format_runtime_cycle_interpretation(runtime_swarm_health.get('latest_cycle_interpretation', {}))}`",
            f"- Latest runtime scan verdict: `{self._format_runtime_scan_summary(runtime_swarm_health.get('latest_runtime_scan_summary', {}))}`",
            f"- Latest runtime scan query/raw/parsed/filtered/tradeable: `{self._format_runtime_scan_counts(runtime_swarm_health.get('latest_runtime_scan_summary', {}))}`",
            f"- Latest runtime scan top exclusions: `{self._format_runtime_scan_exclusions(runtime_swarm_health.get('latest_runtime_scan_summary', {}))}`",
            f"- Runtime dirs scanned / consensus-ready observed: `{runtime_swarm_health.get('total_runtime_dirs_scanned', 0)}` / `{runtime_swarm_health.get('consensus_ready_runs_observed', 0)}`",
            f"- Consensus-ready history verdict: `{runtime_swarm_health.get('consensus_ready_history_verdict', 'unknown')}`",
            f"- Latest consensus-ready run age hours: `{self._format_optional_hours(runtime_swarm_health.get('latest_consensus_ready_run_age_hours'))}`",
            f"- Latest consensus-ready data dir: `{runtime_swarm_health.get('latest_consensus_ready_data_dir', '') or 'none'}`",
            f"- Historical runtime cohort (runs / ready / degraded): `{runtime_swarm_health.get('historical_runs_considered', 0)}` / `{runtime_swarm_health.get('historical_ready_runs', 0)}` / `{runtime_swarm_health.get('historical_degraded_runs', 0)}`",
            f"- Historical provider ok-rates: `{runtime_swarm_health.get('historical_provider_ok_rates', {})}`",
            f"- Historical healthy-provider sets: `{runtime_swarm_health.get('historical_healthy_provider_sets', {})}`",
            (
                f"- Historical failure composition (xai-only / no-healthy / other): "
                f"`{runtime_swarm_health.get('historical_xai_only_runs', 0)}` / "
                f"`{runtime_swarm_health.get('historical_zero_healthy_provider_runs', 0)}` / "
                f"`{runtime_swarm_health.get('historical_other_provider_mix_runs', 0)}`"
            ),
            (
                f"- Historical failure rates (xai-only / no-healthy): "
                f"`{float(runtime_swarm_health.get('historical_xai_only_rate', 0.0) or 0.0):.1%}` / "
                f"`{float(runtime_swarm_health.get('historical_zero_healthy_provider_rate', 0.0) or 0.0):.1%}`"
            ),
            f"- Historical run-level error codes: `{runtime_swarm_health.get('historical_run_error_code_counts', {})}`",
            f"- Most common historical healthy-provider set: `{runtime_swarm_health.get('most_common_historical_healthy_provider_set', 'none')}`",
            f"- Recent runtime cohort (runs / ready / degraded): `{runtime_swarm_health.get('recent_runs_considered', 0)}` / `{runtime_swarm_health.get('recent_ready_runs', 0)}` / `{runtime_swarm_health.get('recent_degraded_runs', 0)}`",
            f"- Recent blocked-run streak: `{runtime_swarm_health.get('recent_runtime_blocked_streak_runs', 0)}`",
            f"- Latest run timestamp / status: `{runtime_swarm_health.get('latest_run_timestamp', '') or 'unknown'}` / `{runtime_swarm_health.get('latest_run_status', '') or 'unknown'}`",
            f"- Latest cycle duration seconds: `{runtime_swarm_health.get('latest_cycle_duration_seconds', 0.0)}`",
            f"- Latest market scan / swarm analysis seconds: `{runtime_swarm_health.get('latest_market_scan_seconds', 0.0)}` / `{runtime_swarm_health.get('latest_swarm_analysis_seconds', 0.0)}`",
            f"- Latest markets found / trades executed: `{runtime_swarm_health.get('latest_markets_found', 0)}` / `{runtime_swarm_health.get('latest_trades_executed', 0)}`",
            f"- Recent avg latest successful models: `{runtime_swarm_health.get('recent_average_latest_successful_model_count', 0.0)}`",
            f"- Latest successful model count: `{runtime_swarm_health.get('latest_successful_model_count', 0)}`",
            f"- Latest abstain reason: `{runtime_swarm_health.get('latest_abstain_reason', '') or 'none'}`",
            f"- Latest measurement boundary: `{runtime_swarm_health.get('latest_measurement_boundary', '') or 'none'}`",
            f"- Latest analysis cohort: `{runtime_swarm_health.get('latest_analysis_cohort', '') or 'none'}`",
            f"- Latest current price present: `{runtime_swarm_health.get('latest_current_price_present', False)}`",
            f"- Latest current price: `{runtime_swarm_health.get('latest_current_price', 'none')}`",
            f"- Latest sigma ratio: `{runtime_swarm_health.get('latest_sigma_ratio', 'none')}`",
            f"- Degraded predictions / single-model control: `{runtime_swarm_health.get('degraded_prediction_count', 0)}` / `{runtime_swarm_health.get('single_model_control_count', 0)}`",
            f"- Runtime error codes: `{runtime_swarm_health.get('error_code_counts', {})}`",
            f"- Recent run-level error codes: `{runtime_swarm_health.get('recent_run_error_code_counts', {})}`",
            f"- Recent provider ok-rates: `{runtime_swarm_health.get('recent_provider_ok_rates', {})}`",
            f"- Persistently healthy / blocked providers: `{runtime_swarm_health.get('persistently_healthy_providers', [])}` / `{runtime_swarm_health.get('persistently_blocked_providers', [])}`",
            f"- Recent runtime primary-cause mix: `{self._format_runtime_primary_cause_counts(runtime_swarm_health.get('recent_primary_cause_counts', {}))}`",
            f"- Most common recent primary cause: `{runtime_swarm_health.get('most_common_recent_primary_cause', '') or 'none'}`",
            f"- Recent healthy-provider sets: `{runtime_swarm_health.get('recent_healthy_provider_sets', {})}`",
            f"- Most common recent healthy-provider set: `{runtime_swarm_health.get('most_common_recent_healthy_provider_set', 'none')}`",
            f"- Single-provider-only runs: `{runtime_swarm_health.get('single_provider_only_runs', 0)}` ({runtime_swarm_health.get('single_provider_only_rate', 0.0):.1%})",
            f"- Recent single-provider-control streak: `{runtime_swarm_health.get('recent_single_provider_control_streak_runs', 0)}`",
            "",
            "## Calibration Credibility",
            "",
            f"- Verdict: `{calibration_snapshot.get('verdict', 'unknown')}`",
            f"- Consensus accuracy / Brier / MAE: `{calibration_snapshot.get('consensus_accuracy', 0.0):.3f}` / `{calibration_snapshot.get('brier_score', 0.0):.4f}` / `{calibration_snapshot.get('mean_absolute_error', 0.0):.4f}`",
            f"- High-confidence cohort: `{self._format_calibration_cohort(calibration_snapshot.get('high_confidence_threshold', 0.5), calibration_snapshot.get('high_confidence', {}))}`",
            f"- Severe-confidence cohort: `{self._format_calibration_cohort(calibration_snapshot.get('severe_confidence_threshold', 0.7), calibration_snapshot.get('severe_confidence', {}))}`",
            f"- Sub-{int(round(float(calibration_snapshot.get('high_confidence_threshold', 0.5) or 0.5) * 100))}% cohort: `{self._format_calibration_cohort('sub', calibration_snapshot.get('low_confidence', {}))}`",
            f"- Confidence gate verdict: `{self._format_confidence_gate_verdict(calibration_snapshot.get('gate_verdict', {}))}`",
            f"- Best simple confidence cap: `{self._format_confidence_gate_row('<=', calibration_snapshot.get('best_cap', {}))}`",
            f"- Best simple confidence floor: `{self._format_confidence_gate_row('>=', calibration_snapshot.get('best_floor', {}))}`",
            f"- Confidence cap sweep: `{self._format_confidence_gate_sweep('<=', calibration_snapshot.get('cap_sweep', []))}`",
            f"- Confidence floor sweep: `{self._format_confidence_gate_sweep('>=', calibration_snapshot.get('floor_sweep', []))}`",
            f"- Confidence monotonicity broken: `{calibration_snapshot.get('confidence_monotonicity_broken', False)}`",
            "",
            "## Edge Quality",
            "",
            f"- Verdict: `{edge_quality_snapshot.get('verdict', 'unknown')}`",
            f"- Gate verdict: `{self._format_confidence_gate_verdict(edge_quality_snapshot.get('gate_verdict', {}))}`",
            f"- Sample bar: `{int(edge_quality_snapshot.get('min_trade_count', 0) or 0)}`",
            f"- Best sampled edge floor: `{self._format_edge_gate_row('>=', edge_quality_snapshot.get('best_floor', {}))}`",
            f"- Best sampled edge cap: `{self._format_edge_gate_row('<=', edge_quality_snapshot.get('best_cap', {}))}`",
            f"- Best low-sample edge floor: `{self._format_edge_gate_row('>=', edge_quality_snapshot.get('best_low_sample_floor', {}))}`",
            f"- Low-edge cohort: `{self._format_edge_quality_cohort('<=10', edge_quality_snapshot.get('low_edge', {}))}`",
            f"- High-edge cohort: `{self._format_edge_quality_cohort('>=20', edge_quality_snapshot.get('high_edge', {}))}`",
            f"- Higher edge beats low edge: `{edge_quality_snapshot.get('high_edge_beats_low_edge', False)}`",
            f"- Edge cap sweep: `{self._format_edge_gate_sweep('<=', edge_quality_snapshot.get('cap_sweep', []))}`",
            f"- Edge floor sweep: `{self._format_edge_gate_sweep('>=', edge_quality_snapshot.get('floor_sweep', []))}`",
            "",
            "## Timeframe + Edge Pockets",
            "",
            f"- Verdict: `{edge_timeframe_snapshot.get('verdict', 'unknown')}`",
            f"- Gate verdict: `{self._format_confidence_gate_verdict(edge_timeframe_snapshot.get('gate_verdict', {}))}`",
            f"- Sample bar: `{int(edge_timeframe_snapshot.get('min_trade_count', 0) or 0)}`",
            f"- Best sampled timeframe-edge pocket: `{self._format_edge_timeframe_row(edge_timeframe_snapshot.get('best_sampled_pocket', {}))}`",
            f"- Best low-sample timeframe-edge pocket: `{self._format_edge_timeframe_row(edge_timeframe_snapshot.get('best_low_sample_pocket', {}))}`",
            f"- Positive sampled / low-sample timeframe-edge pockets: `{int(edge_timeframe_snapshot.get('positive_sampled_pocket_count', 0) or 0)}` / `{int(edge_timeframe_snapshot.get('positive_low_sample_pocket_count', 0) or 0)}`",
            f"- Top timeframe-edge pockets: `{self._format_edge_timeframe_rows(edge_timeframe_snapshot.get('top_rows', []))}`",
            "",
            "## Market Archetype Pockets",
            "",
            f"- Verdict: `{market_archetype_snapshot.get('verdict', 'unknown')}`",
            f"- Gate verdict: `{self._format_confidence_gate_verdict(market_archetype_snapshot.get('gate_verdict', {}))}`",
            f"- Sample bar: `{int(market_archetype_snapshot.get('min_trade_count', 0) or 0)}`",
            f"- Best sampled market-archetype pocket: `{self._format_market_archetype_row(market_archetype_snapshot.get('best_sampled_pocket', {}))}`",
            f"- Best low-sample market-archetype pocket: `{self._format_market_archetype_row(market_archetype_snapshot.get('best_low_sample_pocket', {}))}`",
            f"- Positive sampled / low-sample market-archetype pockets: `{int(market_archetype_snapshot.get('positive_sampled_pocket_count', 0) or 0)}` / `{int(market_archetype_snapshot.get('positive_low_sample_pocket_count', 0) or 0)}`",
            f"- Top market-archetype pockets: `{self._format_market_archetype_rows(market_archetype_snapshot.get('top_rows', []))}`",
            "",
            "## Entry Price Pockets",
            "",
            f"- Verdict: `{entry_price_snapshot.get('verdict', 'unknown')}`",
            f"- Gate verdict: `{self._format_confidence_gate_verdict(entry_price_snapshot.get('gate_verdict', {}))}`",
            f"- Sample bar: `{int(entry_price_snapshot.get('min_trade_count', 0) or 0)}`",
            f"- Best sampled entry-price pocket: `{self._format_entry_price_row(entry_price_snapshot.get('best_sampled_pocket', {}))}`",
            f"- Best low-sample entry-price pocket: `{self._format_entry_price_row(entry_price_snapshot.get('best_low_sample_pocket', {}))}`",
            f"- Cheap-tail all cohort: `{self._format_entry_price_row(entry_price_snapshot.get('cheap_tail_all', {}))}`",
            f"- Cheap-tail bullish-NO cohort: `{self._format_entry_price_row(entry_price_snapshot.get('cheap_tail_bullish_no', {}))}`",
            f"- Cheap-tail bullish-NO fast cohort: `{self._format_entry_price_row(entry_price_snapshot.get('cheap_tail_bullish_no_fast', {}))}`",
            f"- Best low-sample patch concentration: `{self._format_patch_concentration_row(entry_price_snapshot.get('best_low_sample_concentration', {}))}`",
            f"- Cheap-tail bullish-NO fast concentration: `{self._format_patch_concentration_row(entry_price_snapshot.get('cheap_tail_bullish_no_fast_concentration', {}))}`",
            f"- Low-sample patch independence verdict: `{self._format_confidence_gate_verdict(entry_price_snapshot.get('best_low_sample_independence_verdict', {}))}`",
            f"- Cheap-tail fast-subset independence verdict: `{self._format_confidence_gate_verdict(entry_price_snapshot.get('cheap_tail_bullish_no_fast_independence_verdict', {}))}`",
            f"- Positive sampled / low-sample entry-price pockets: `{int(entry_price_snapshot.get('positive_sampled_pocket_count', 0) or 0)}` / `{int(entry_price_snapshot.get('positive_low_sample_pocket_count', 0) or 0)}`",
            f"- Top entry-price pockets: `{self._format_entry_price_rows(entry_price_snapshot.get('top_rows', []))}`",
            "",
            "## Directional Credibility",
            "",
            f"- Verdict: `{direction_snapshot.get('verdict', 'unknown')}`",
            f"- Direction gate verdict: `{self._format_confidence_gate_verdict(direction_snapshot.get('gate_verdict', {}))}`",
            f"- YES cohort: `{self._format_direction_row('YES', direction_snapshot.get('yes', {}))}`",
            f"- NO cohort: `{self._format_direction_row('NO', direction_snapshot.get('no', {}))}`",
            f"- Best direction gate: `{self._format_best_direction(direction_snapshot.get('best_direction', {}))}`",
            f"- Direction-timeframe pocket verdict: `{self._format_confidence_gate_verdict(direction_snapshot.get('pocket_verdict', {}))}`",
            f"- Best direction-timeframe pocket: `{self._format_best_direction_timeframe(direction_snapshot.get('best_direction_timeframe', {}))}`",
            f"- Worst direction-timeframe drag pocket: `{self._format_drag_direction_timeframe(direction_snapshot.get('worst_direction_timeframe', {}))}`",
            f"- Top directional drag pockets: `{self._format_drag_direction_timeframe_rows(direction_snapshot.get('top_negative_direction_timeframes', []))}`",
            f"- Top-two directional drag share: `{float(direction_snapshot.get('top_two_directional_drag_share', 0.0) or 0.0):.1%}`",
            f"- Exclusion rescue verdict: `{self._format_confidence_gate_verdict(direction_snapshot.get('exclusion_rescue', {}))}`",
            f"- Exclusion rescue scenarios: `{self._format_exclusion_rescue_rows(direction_snapshot.get('exclusion_rescue', {}).get('scenarios', []))}`",
            "",
            "## Composite Policy Rescue",
            "",
            f"- Verdict: `{policy_rescue_snapshot.get('verdict', 'unknown')}`",
            f"- Gate verdict: `{self._format_confidence_gate_verdict(policy_rescue_snapshot.get('gate_verdict', {}))}`",
            f"- Sample bar: `{int(policy_rescue_snapshot.get('min_trade_count', 0) or 0)}`",
            f"- Best sampled composite policy: `{self._format_policy_rescue_row(policy_rescue_snapshot.get('best_sampled_policy', {}))}`",
            f"- Best low-sample composite policy: `{self._format_policy_rescue_row(policy_rescue_snapshot.get('best_low_sample_policy', {}))}`",
            f"- Positive sampled / low-sample composite policies: `{int(policy_rescue_snapshot.get('positive_sampled_policy_count', 0) or 0)}` / `{int(policy_rescue_snapshot.get('positive_low_sample_policy_count', 0) or 0)}`",
            f"- Top composite policies: `{self._format_policy_rescue_rows(policy_rescue_snapshot.get('top_rows', []))}`",
            "",
            "## Risk/Return",
            "",
            f"- Expectancy per closed trade: `${risk_return.get('expectancy_per_closed_trade', 0.0):+.2f}`",
            f"- Avg win / avg loss: `${risk_return.get('avg_win', 0.0):+.2f}` / `${risk_return.get('avg_loss', 0.0):+.2f}`",
            f"- Payoff ratio: `{risk_return.get('payoff_ratio', 'none')}`",
            f"- PnL to max drawdown: `{risk_return.get('pnl_to_drawdown', 'none')}`",
            f"- Best / worst timeframe: `{self._format_risk_timeframe(risk_return.get('best_timeframe', {}))}` / `{self._format_risk_timeframe(risk_return.get('worst_timeframe', {}))}`",
            "",
            "## Performance",
            "",
            f"- Closed trades: `{perf.get('closed_trades', 0)}`",
            f"- Win rate: `{perf.get('win_rate', 0.0):.1%}`",
            f"- Total PnL: `${perf.get('total_pnl', 0.0):+.2f}`",
            f"- Max drawdown: `${perf.get('max_drawdown', 0.0):.2f}`",
            f"- Profit factor: `{perf.get('profit_factor', 0)}`",
            f"- Positive timeframe lanes: `{self._format_timeframe_pnl_rows(timeframe_snapshot.get('positive', []))}`",
            f"- Negative timeframe lanes: `{self._format_timeframe_pnl_rows(timeframe_snapshot.get('negative', []))}`",
            f"- PnL concentrated in one positive timeframe: `{timeframe_snapshot.get('single_positive_timeframe', False)}`",
            "",
            "## Replay Cohort",
            "",
            f"- Holdout gate feasible today: `{replay.get('gate_feasible', False)}`",
            f"- Holdout raw trades: `{replay.get('holdout_total_trades', holdout_diag.get('total_trades', 0))}`",
            f"- Diagnostic widened holdout support: `{holdout_probe.get('any_filtered_holdout', False)}`",
            f"- Diagnostic widened holdout sweep: `{self._format_holdout_probe_rows(holdout_probe.get('ratios', []))}`",
            f"- Active cohort trades / markets: `{active_diag.get('total_trades', 0)}` / `{active_diag.get('unique_markets', 0)}`",
            f"- Active cohort entry span: `{active_diag.get('entry_span_start', '') or 'unknown'}` -> `{active_diag.get('entry_span_end', '') or 'unknown'}`",
            f"- Active cohort symbols: `{active_diag.get('symbols', {})}`",
            f"- Holdout trades / markets: `{holdout_diag.get('total_trades', 0)}` / `{holdout_diag.get('unique_markets', 0)}`",
            f"- Holdout exclusion reasons: `{holdout_diag.get('exclusion_reasons', {})}`",
            "",
            "## Inventory",
            "",
            f"- Inventory refresh mode: `{inventory.get('refresh_mode', 'unknown')}`",
            f"- Inventory source generated at: `{inventory.get('source_generated_at', '') or 'live_scan'}`",
            f"- Inventory freshness verdict: `{inventory_diagnostics.get('inventory_freshness_verdict', 'unknown')}`",
            f"- Inventory snapshot age hours: `{self._format_optional_hours(inventory_diagnostics.get('inventory_snapshot_age_hours'))}`",
            f"- Inventory freshness threshold hours: `{self._format_optional_hours(inventory_diagnostics.get('inventory_freshness_threshold_hours'))}`",
            f"- Inventory fresh enough for research summary: `{inventory_diagnostics.get('fresh_enough_for_research_summary', False)}`",
            f"- Strict tradeable markets: `{inventory.get('strict', {}).get('tradeable_markets', 0)}`",
            f"- Broad tradeable markets: `{inventory.get('broad', {}).get('tradeable_markets', 0)}`",
            f"- Strict share of broad surface: `{self._format_optional_percent(inventory_diagnostics.get('strict_share_of_broad'))}`",
            f"- Broad minus strict markets: `{inventory_diagnostics.get('broad_minus_strict_markets', 0)}`",
            f"- Inventory funnel read: `{inventory_diagnostics.get('inventory_thesis', 'unknown')}`",
            f"- Strict ETH short-horizon markets: `{inventory_diagnostics.get('strict_eth_short_horizon_markets', 0)}`",
            f"- Broad ETH short-horizon markets: `{inventory_diagnostics.get('broad_eth_short_horizon_markets', 0)}`",
            f"- Broad BTC long-dated markets: `{inventory_diagnostics.get('broad_btc_long_dated_markets', 0)}`",
            f"- Broad ETH long-dated markets: `{inventory_diagnostics.get('broad_eth_long_dated_markets', 0)}`",
            f"- Thesis surface share of broad: `{self._format_optional_percent(inventory_diagnostics.get('thesis_surface_share_of_broad'))}`",
            f"- Strict thesis capture rate: `{self._format_optional_percent(inventory_diagnostics.get('strict_thesis_capture_rate'))}`",
            f"- BTC long-dated to ETH short-horizon ratio: `{self._format_optional_ratio(inventory_diagnostics.get('btc_long_dated_to_eth_short_ratio'))}`",
            f"- Top strict exclusion reasons: `{self._format_count_rows(inventory_diagnostics.get('top_strict_exclusion_reasons', []))}`",
            f"- Top broad exclusion reasons: `{self._format_count_rows(inventory_diagnostics.get('top_broad_exclusion_reasons', []))}`",
            f"- Dominant broad symbol / expiry bucket: `{self._format_inventory_mix(inventory_diagnostics.get('dominant_broad_symbol'), inventory_diagnostics.get('dominant_broad_symbol_share'))}` / `{self._format_inventory_mix(inventory_diagnostics.get('dominant_broad_expiry_bucket'), inventory_diagnostics.get('dominant_broad_expiry_share'))}`",
            f"- Strict exclusion reasons: `{inventory.get('strict', {}).get('telemetry', {}).get('exclusion_reasons', {})}`",
            "",
            "## Archive Context",
            "",
        ])

        archive_context = edge.get("archive_context", {})
        if archive_context.get("enabled"):
            archive_current = archive_context.get("current_config", {})
            archive_score = archive_current.get("score", {})
            archive_replay = archive_current.get("replay", {})
            lines.extend([
                f"- Context data dirs: `{len(archive_context.get('data_dirs', []))}`",
                f"- Current-config archive score: `{float(archive_score.get('score', 0.0)):.2f}`",
                f"- Current-config archive PnL: `${float(archive_score.get('total_pnl', 0.0)):+.2f}`",
                f"- Current-config archive holdout trades: `{int(archive_replay.get('holdout', {}).get('filtered_trades', 0))}`",
                "",
            ])
        else:
            lines.extend([
                "- Archive context: `disabled`",
                "",
            ])

        lines.extend([
            "## Team",
            "",
        ])

        for role in manifest.get("roles", []):
            lines.append(f"- `{role['title']}`: {role['mandate']}")

        lines.extend(["", "## Blockers", ""])
        for blocker in blockers:
            lines.append(f"- `{blocker['title']}`: {blocker['evidence']}")
            lines.append(f"  - {blocker['implication']}")

        lines.extend(["", "## Priorities", ""])
        for priority in priorities:
            lines.append(f"- `{priority['title']}`: {priority['rationale']}")
            for action in priority.get("actions", []):
                lines.append(f"  - {action}")

        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    @staticmethod
    def _normalize_path_set(paths: List[str]) -> set[str]:
        normalized = set()
        for item in paths:
            path = Path(item)
            normalized.add(str(path.resolve()) if path.exists() else str(path))
        return normalized

    def _load_existing_report(self) -> Dict[str, Any]:
        path = self.output_dir / "edge_report.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _format_holdout_probe_rows(rows: Any) -> str:
        if not isinstance(rows, list) or not rows:
            return "none"
        formatted: List[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ratio = QuantResearchTeam._safe_float(row.get("holdout_ratio"), 0.0)
            raw = int(row.get("raw_holdout_trades", 0) or 0)
            filtered = int(row.get("filtered_holdout_trades", 0) or 0)
            formatted.append(f"{int(round(ratio * 100))}% raw={raw} filtered={filtered}")
        return "; ".join(formatted) if formatted else "none"

    @staticmethod
    def _summarize_timeframe_pnl(perf: Dict[str, Any]) -> Dict[str, Any]:
        by_timeframe = perf.get("by_timeframe", {}) if isinstance(perf, dict) else {}
        positive: List[Dict[str, Any]] = []
        negative: List[Dict[str, Any]] = []
        for timeframe, row in by_timeframe.items():
            if not isinstance(row, dict):
                continue
            pnl = QuantResearchTeam._safe_float(row.get("pnl"), 0.0)
            count = int(row.get("count", 0) or 0)
            item = {
                "timeframe": str(timeframe),
                "pnl": round(pnl, 2),
                "count": count,
            }
            if pnl > 0:
                positive.append(item)
            elif pnl < 0:
                negative.append(item)
        positive.sort(key=lambda item: (-item["pnl"], item["timeframe"]))
        negative.sort(key=lambda item: (item["pnl"], item["timeframe"]))
        return {
            "positive": positive,
            "negative": negative,
            "single_positive_timeframe": len(positive) == 1,
        }

    @staticmethod
    def _format_timeframe_pnl_rows(rows: Any) -> str:
        if not isinstance(rows, list) or not rows:
            return "none"
        formatted: List[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            timeframe = str(row.get("timeframe", "unknown"))
            pnl = QuantResearchTeam._safe_float(row.get("pnl"), 0.0)
            count = int(row.get("count", 0) or 0)
            formatted.append(f"{timeframe} {pnl:+.2f} ({count} trades)")
        return "; ".join(formatted) if formatted else "none"

    @staticmethod
    def _format_calibration_cohort(threshold: Any, row: Any) -> str:
        if not isinstance(row, dict) or int(row.get("count", 0) or 0) <= 0:
            return "none"
        threshold_label = (
            f">={float(threshold or 0.0):.0%}"
            if threshold != "sub"
            else "below threshold"
        )
        return (
            f"{threshold_label}: {int(row.get('count', 0) or 0)} trades, "
            f"WR {float(row.get('win_rate', 0.0) or 0.0):.1%}, "
            f"PnL ${float(row.get('total_pnl', 0.0) or 0.0):+.2f}, "
            f"avg p={float(row.get('avg_predicted_probability', 0.0) or 0.0):.3f}, "
            f"gap={float(row.get('overconfidence_gap', 0.0) or 0.0):+.3f}"
        )

    @staticmethod
    def _normalize_confidence_gate_row(row: Any) -> Dict[str, Any]:
        if not isinstance(row, dict):
            return {}
        return {
            "threshold": float(row.get("threshold", 0.0) or 0.0),
            "count": int(row.get("count", 0) or 0),
            "win_rate": round(float(row.get("win_rate", 0.0) or 0.0), 3),
            "total_pnl": round(float(row.get("total_pnl", 0.0) or 0.0), 2),
            "avg_predicted_probability": round(float(row.get("avg_predicted_probability", 0.0) or 0.0), 3),
            "overconfidence_gap": round(float(row.get("overconfidence_gap", 0.0) or 0.0), 3),
        }

    @staticmethod
    def _normalize_edge_gate_row(row: Any) -> Dict[str, Any]:
        if not isinstance(row, dict):
            return {}
        return {
            "threshold": float(row.get("threshold", 0.0) or 0.0),
            "count": int(row.get("count", 0) or 0),
            "win_rate": round(float(row.get("win_rate", 0.0) or 0.0), 3),
            "total_pnl": round(float(row.get("total_pnl", 0.0) or 0.0), 2),
            "avg_edge_at_entry": round(float(row.get("avg_edge_at_entry", 0.0) or 0.0), 2),
            "avg_predicted_probability": round(float(row.get("avg_predicted_probability", 0.0) or 0.0), 3),
        }

    @staticmethod
    def _normalize_confidence_gate_verdict(row: Any) -> Dict[str, Any]:
        if not isinstance(row, dict):
            return {"status": "unknown", "reason_codes": []}
        return {
            "status": str(row.get("status", "unknown") or "unknown"),
            "reason_codes": list(row.get("reason_codes", []) or []),
        }

    @staticmethod
    def _normalize_direction_row(row: Any) -> Dict[str, Any]:
        if not isinstance(row, dict):
            return {}
        return {
            "count": int(row.get("count", 0) or 0),
            "win_rate": round(float(row.get("win_rate", 0.0) or 0.0), 3),
            "total_pnl": round(float(row.get("total_pnl", 0.0) or 0.0), 2),
            "avg_predicted_probability": round(float(row.get("avg_predicted_probability", 0.0) or 0.0), 3),
        }

    @staticmethod
    def _normalize_policy_rescue_row(row: Any) -> Dict[str, Any]:
        if not isinstance(row, dict):
            return {}
        return {
            "direction": str(row.get("direction", "") or ""),
            "timeframe": str(row.get("timeframe", "") or ""),
            "confidence_filter": str(row.get("confidence_filter", "") or ""),
            "active_filters": list(row.get("active_filters", []) or []),
            "count": int(row.get("count", 0) or 0),
            "win_rate": round(float(row.get("win_rate", 0.0) or 0.0), 3),
            "total_pnl": round(float(row.get("total_pnl", 0.0) or 0.0), 2),
            "avg_predicted_probability": round(float(row.get("avg_predicted_probability", 0.0) or 0.0), 3),
        }

    @staticmethod
    def _normalize_edge_timeframe_row(row: Any) -> Dict[str, Any]:
        if not isinstance(row, dict):
            return {}
        return {
            "timeframe": str(row.get("timeframe", "") or ""),
            "edge_mode": str(row.get("edge_mode", "") or ""),
            "edge_filter": str(row.get("edge_filter", "") or ""),
            "threshold": float(row.get("threshold", 0.0) or 0.0),
            "count": int(row.get("count", 0) or 0),
            "win_rate": round(float(row.get("win_rate", 0.0) or 0.0), 3),
            "total_pnl": round(float(row.get("total_pnl", 0.0) or 0.0), 2),
            "avg_edge_at_entry": round(float(row.get("avg_edge_at_entry", 0.0) or 0.0), 2),
            "avg_predicted_probability": round(float(row.get("avg_predicted_probability", 0.0) or 0.0), 3),
        }

    @staticmethod
    def _normalize_market_archetype_row(row: Any) -> Dict[str, Any]:
        if not isinstance(row, dict):
            return {}
        return {
            "timeframe": str(row.get("timeframe", "") or ""),
            "market_type": str(row.get("market_type", "") or ""),
            "direction": str(row.get("direction", "") or ""),
            "count": int(row.get("count", 0) or 0),
            "win_rate": round(float(row.get("win_rate", 0.0) or 0.0), 3),
            "total_pnl": round(float(row.get("total_pnl", 0.0) or 0.0), 2),
            "avg_predicted_probability": round(float(row.get("avg_predicted_probability", 0.0) or 0.0), 3),
        }

    @staticmethod
    def _normalize_entry_price_row(row: Any) -> Dict[str, Any]:
        if not isinstance(row, dict):
            return {}
        return {
            "price_band": str(row.get("price_band", "") or ""),
            "market_type": str(row.get("market_type", "") or ""),
            "direction": str(row.get("direction", "") or ""),
            "timeframe_scope": str(row.get("timeframe_scope", "") or ""),
            "count": int(row.get("count", 0) or 0),
            "win_rate": round(float(row.get("win_rate", 0.0) or 0.0), 3),
            "total_pnl": round(float(row.get("total_pnl", 0.0) or 0.0), 2),
            "avg_entry_price": round(float(row.get("avg_entry_price", 0.0) or 0.0), 3),
            "avg_edge": round(float(row.get("avg_edge", 0.0) or 0.0), 2),
        }

    @staticmethod
    def _normalize_patch_concentration_row(row: Any) -> Dict[str, Any]:
        if not isinstance(row, dict):
            return {}
        share = row.get("largest_win_share_of_total_pnl", None)
        return {
            "count": int(row.get("count", 0) or 0),
            "unique_markets": int(row.get("unique_markets", 0) or 0),
            "largest_win_pnl": round(float(row.get("largest_win_pnl", 0.0) or 0.0), 2),
            "largest_loss_pnl": round(float(row.get("largest_loss_pnl", 0.0) or 0.0), 2),
            "total_pnl": round(float(row.get("total_pnl", 0.0) or 0.0), 2),
            "largest_win_share_of_total_pnl": round(float(share), 3) if share is not None else None,
            "residual_pnl_without_largest_win": round(float(row.get("residual_pnl_without_largest_win", 0.0) or 0.0), 2),
            "survives_without_largest_win": bool(row.get("survives_without_largest_win", False)),
        }

    @staticmethod
    def _build_patch_independence_verdict(row: Any) -> Dict[str, Any]:
        if not isinstance(row, dict) or int(row.get("count", 0) or 0) <= 0:
            return {
                "status": "NO_PATCH_SAMPLE",
                "reason_codes": ["no_patch_sample"],
            }
        reason_codes: List[str] = []
        count = int(row.get("count", 0) or 0)
        unique_markets = int(row.get("unique_markets", 0) or 0)
        share = row.get("largest_win_share_of_total_pnl", None)
        if count < 5:
            reason_codes.append("low_trade_count")
        if unique_markets <= 1:
            reason_codes.append("single_market_patch")
        elif unique_markets <= 2:
            reason_codes.append("two_or_fewer_markets")
        if not bool(row.get("survives_without_largest_win", False)):
            reason_codes.append("fails_without_top_win")
        if share is not None:
            share_value = float(share)
            if share_value > 1.0:
                reason_codes.append("top_win_exceeds_total_patch_pnl")
            elif share_value > 0.5:
                reason_codes.append("top_win_dominates_patch_pnl")
        return {
            "status": "INDEPENDENT_PATCH" if not reason_codes else "NON_INDEPENDENT_PATCH",
            "reason_codes": reason_codes,
        }

    @staticmethod
    def _format_confidence_gate_row(prefix: str, row: Any) -> str:
        if not isinstance(row, dict) or int(row.get("count", 0) or 0) <= 0:
            return "none"
        threshold = float(row.get("threshold", 0.0) or 0.0)
        return (
            f"{prefix}{threshold:.0%}: {int(row.get('count', 0) or 0)} trades, "
            f"WR {float(row.get('win_rate', 0.0) or 0.0):.1%}, "
            f"PnL ${float(row.get('total_pnl', 0.0) or 0.0):+.2f}"
        )

    @staticmethod
    def _format_confidence_gate_sweep(prefix: str, rows: Any) -> str:
        if not isinstance(rows, list) or not rows:
            return "none"
        formatted = [
            QuantResearchTeam._format_confidence_gate_row(prefix, row)
            for row in rows
            if isinstance(row, dict)
        ]
        filtered = [item for item in formatted if item != "none"]
        return "; ".join(filtered) if filtered else "none"

    @staticmethod
    def _format_edge_gate_row(prefix: str, row: Any) -> str:
        if not isinstance(row, dict) or int(row.get("count", 0) or 0) <= 0:
            return "none"
        threshold = float(row.get("threshold", 0.0) or 0.0)
        return (
            f"{prefix}{threshold:g}: {int(row.get('count', 0) or 0)} trades, "
            f"WR {float(row.get('win_rate', 0.0) or 0.0):.1%}, "
            f"PnL ${float(row.get('total_pnl', 0.0) or 0.0):+.2f}, "
            f"avg edge {float(row.get('avg_edge_at_entry', 0.0) or 0.0):.2f}"
        )

    @staticmethod
    def _format_edge_gate_sweep(prefix: str, rows: Any) -> str:
        if not isinstance(rows, list) or not rows:
            return "none"
        formatted = [
            QuantResearchTeam._format_edge_gate_row(prefix, row)
            for row in rows
            if isinstance(row, dict)
        ]
        filtered = [item for item in formatted if item != "none"]
        return "; ".join(filtered) if filtered else "none"

    @staticmethod
    def _format_edge_quality_cohort(label: str, row: Any) -> str:
        if not isinstance(row, dict) or int(row.get("count", 0) or 0) <= 0:
            return "none"
        return (
            f"{label}: {int(row.get('count', 0) or 0)} trades, "
            f"WR {float(row.get('win_rate', 0.0) or 0.0):.1%}, "
            f"PnL ${float(row.get('total_pnl', 0.0) or 0.0):+.2f}, "
            f"avg edge {float(row.get('avg_edge_at_entry', 0.0) or 0.0):.2f}"
        )

    @staticmethod
    def _format_confidence_gate_verdict(row: Any) -> str:
        if not isinstance(row, dict):
            return "unknown"
        status = str(row.get("status", "unknown") or "unknown")
        reasons = list(row.get("reason_codes", []) or [])
        if reasons:
            return f"{status}; reasons={reasons}"
        return status

    @staticmethod
    def _format_direction_row(label: str, row: Any) -> str:
        if not isinstance(row, dict) or int(row.get("count", 0) or 0) <= 0:
            return "none"
        return (
            f"{label}: {int(row.get('count', 0) or 0)} trades, "
            f"WR {float(row.get('win_rate', 0.0) or 0.0):.1%}, "
            f"PnL ${float(row.get('total_pnl', 0.0) or 0.0):+.2f}, "
            f"avg p={float(row.get('avg_predicted_probability', 0.0) or 0.0):.3f}"
        )

    @staticmethod
    def _format_best_direction(row: Any) -> str:
        if not isinstance(row, dict) or not str(row.get("direction", "") or ""):
            return "none"
        direction = str(row.get("direction", "unknown") or "unknown")
        return (
            f"{direction}: {int(row.get('count', 0) or 0)} trades, "
            f"WR {float(row.get('win_rate', 0.0) or 0.0):.1%}, "
            f"PnL ${float(row.get('total_pnl', 0.0) or 0.0):+.2f}"
        )

    @staticmethod
    def _format_best_direction_timeframe(row: Any) -> str:
        if not isinstance(row, dict) or not str(row.get("direction", "") or ""):
            return "none"
        direction = str(row.get("direction", "unknown") or "unknown")
        timeframe = str(row.get("timeframe", "unknown") or "unknown")
        return (
            f"{direction} / {timeframe}: {int(row.get('count', 0) or 0)} trades, "
            f"WR {float(row.get('win_rate', 0.0) or 0.0):.1%}, "
            f"PnL ${float(row.get('total_pnl', 0.0) or 0.0):+.2f}"
        )

    @staticmethod
    def _format_policy_rescue_row(row: Any) -> str:
        if not isinstance(row, dict) or not row:
            return "none"
        direction = str(row.get("direction", "ALL") or "ALL")
        timeframe = str(row.get("timeframe", "ALL") or "ALL")
        confidence_filter = str(row.get("confidence_filter", "ALL") or "ALL")
        return (
            f"{direction} / {timeframe} / {confidence_filter}: "
            f"{int(row.get('count', 0) or 0)} trades, "
            f"WR {float(row.get('win_rate', 0.0) or 0.0):.1%}, "
            f"PnL ${float(row.get('total_pnl', 0.0) or 0.0):+.2f}"
        )

    @staticmethod
    def _format_policy_rescue_rows(rows: Any) -> str:
        if not isinstance(rows, list) or not rows:
            return "none"
        formatted = [
            QuantResearchTeam._format_policy_rescue_row(row)
            for row in rows
            if isinstance(row, dict)
        ]
        filtered = [item for item in formatted if item != "none"]
        return "; ".join(filtered) if filtered else "none"

    @staticmethod
    def _format_edge_timeframe_row(row: Any) -> str:
        if not isinstance(row, dict) or not row:
            return "none"
        timeframe = str(row.get("timeframe", "unknown") or "unknown")
        edge_filter = str(row.get("edge_filter", "") or "")
        if not edge_filter:
            edge_mode = str(row.get("edge_mode", "") or "")
            threshold = float(row.get("threshold", 0.0) or 0.0)
            comparator = ">=" if edge_mode == "floor" else "<="
            edge_filter = f"{edge_mode}{comparator}{threshold:g}"
        return (
            f"{timeframe} / {edge_filter}: "
            f"{int(row.get('count', 0) or 0)} trades, "
            f"WR {float(row.get('win_rate', 0.0) or 0.0):.1%}, "
            f"PnL ${float(row.get('total_pnl', 0.0) or 0.0):+.2f}, "
            f"avg edge {float(row.get('avg_edge_at_entry', 0.0) or 0.0):.2f}"
        )

    @staticmethod
    def _format_edge_timeframe_rows(rows: Any) -> str:
        if not isinstance(rows, list) or not rows:
            return "none"
        formatted = [
            QuantResearchTeam._format_edge_timeframe_row(row)
            for row in rows
            if isinstance(row, dict)
        ]
        filtered = [item for item in formatted if item != "none"]
        return "; ".join(filtered) if filtered else "none"

    @staticmethod
    def _format_market_archetype_row(row: Any) -> str:
        if not isinstance(row, dict) or not row:
            return "none"
        timeframe = str(row.get("timeframe", "unknown") or "unknown")
        market_type = str(row.get("market_type", "unknown") or "unknown")
        direction = str(row.get("direction", "unknown") or "unknown")
        return (
            f"{timeframe} / {market_type} / {direction}: "
            f"{int(row.get('count', 0) or 0)} trades, "
            f"WR {float(row.get('win_rate', 0.0) or 0.0):.1%}, "
            f"PnL ${float(row.get('total_pnl', 0.0) or 0.0):+.2f}"
        )

    @staticmethod
    def _format_market_archetype_rows(rows: Any) -> str:
        if not isinstance(rows, list) or not rows:
            return "none"
        formatted = [
            QuantResearchTeam._format_market_archetype_row(row)
            for row in rows
            if isinstance(row, dict)
        ]
        filtered = [item for item in formatted if item != "none"]
        return "; ".join(filtered) if filtered else "none"

    @staticmethod
    def _format_entry_price_row(row: Any) -> str:
        if not isinstance(row, dict) or not row:
            return "none"
        price_band = str(row.get("price_band", "unknown") or "unknown")
        market_type = str(row.get("market_type", "unknown") or "unknown")
        direction = str(row.get("direction", "unknown") or "unknown")
        timeframe_scope = str(row.get("timeframe_scope", "ALL") or "ALL")
        label = f"{price_band} / {market_type} / {direction}"
        if timeframe_scope not in {"", "ALL"}:
            label = f"{label} / {timeframe_scope}"
        return (
            f"{label}: "
            f"{int(row.get('count', 0) or 0)} trades, "
            f"WR {float(row.get('win_rate', 0.0) or 0.0):.1%}, "
            f"PnL ${float(row.get('total_pnl', 0.0) or 0.0):+.2f}, "
            f"avg px {float(row.get('avg_entry_price', 0.0) or 0.0):.3f}, "
            f"avg edge {float(row.get('avg_edge', 0.0) or 0.0):.2f}"
        )

    @staticmethod
    def _format_entry_price_rows(rows: Any) -> str:
        if not isinstance(rows, list) or not rows:
            return "none"
        formatted = [
            QuantResearchTeam._format_entry_price_row(row)
            for row in rows
            if isinstance(row, dict)
        ]
        filtered = [item for item in formatted if item != "none"]
        return "; ".join(filtered) if filtered else "none"

    @staticmethod
    def _format_patch_concentration_row(row: Any) -> str:
        if not isinstance(row, dict) or int(row.get("count", 0) or 0) <= 0:
            return "none"
        share = row.get("largest_win_share_of_total_pnl", None)
        share_text = f"{float(share):.1%}" if share is not None else "n/a"
        return (
            f"{int(row.get('count', 0) or 0)} trades / {int(row.get('unique_markets', 0) or 0)} markets, "
            f"top win ${float(row.get('largest_win_pnl', 0.0) or 0.0):+.2f}, "
            f"largest loss ${float(row.get('largest_loss_pnl', 0.0) or 0.0):+.2f}, "
            f"residual ex-best ${float(row.get('residual_pnl_without_largest_win', 0.0) or 0.0):+.2f}, "
            f"top-win share {share_text}, "
            f"survives ex-best {bool(row.get('survives_without_largest_win', False))}"
        )

    @staticmethod
    def _format_surviving_patch_promotability(row: Any) -> str:
        if not isinstance(row, dict):
            return "unknown"
        status = str(row.get("status", "unknown") or "unknown")
        reasons = list(row.get("reason_codes", []) or [])
        if reasons:
            return f"{status}; reasons={reasons}"
        return status

    @staticmethod
    def _format_active_edge_configuration(row: Any) -> str:
        if not isinstance(row, dict) or not row:
            return "none"
        label = str(row.get("label", "unknown") or "unknown")
        return (
            f"{label} {float(row.get('total_pnl', 0.0) or 0.0):+.2f} "
            f"({int(row.get('filtered_trades', 0) or 0)} trades, "
            f"replay={bool(row.get('replay_accepted', False))}, "
            f"holdout={int(row.get('holdout_trades', 0) or 0)})"
        )

    @staticmethod
    def _format_active_edge_snapshot(row: Any) -> str:
        if not isinstance(row, dict):
            return "unknown"
        status = str(row.get("status", "unknown") or "unknown")
        reasons = list(row.get("reason_codes", []) or [])
        if reasons:
            return f"{status}; reasons={reasons}"
        return status

    @staticmethod
    def _format_runtime_scan_summary(row: Any) -> str:
        if not isinstance(row, dict):
            return "unknown"
        status = str(row.get("status", "unknown") or "unknown")
        reasons = list(row.get("reason_codes", []) or [])
        if reasons:
            return f"{status}; reasons={reasons}"
        return status

    @staticmethod
    def _format_runtime_scan_counts(row: Any) -> str:
        if not isinstance(row, dict):
            return "none"
        return (
            f"{int(row.get('query_count', 0) or 0)} / "
            f"{int(row.get('raw_records', 0) or 0)} / "
            f"{int(row.get('parsed', 0) or 0)} / "
            f"{int(row.get('filtered', 0) or 0)} / "
            f"{int(row.get('tradeable', 0) or 0)}"
        )

    @staticmethod
    def _format_runtime_scan_exclusions(row: Any) -> str:
        if not isinstance(row, dict):
            return "none"
        exclusions = row.get("top_exclusion_reasons", [])
        if not isinstance(exclusions, list) or not exclusions:
            return "none"
        formatted = []
        for item in exclusions:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "") or "")
            count = int(item.get("count", 0) or 0)
            if not key:
                continue
            formatted.append(f"{key}: {count}")
        return "; ".join(formatted) if formatted else "none"

    @staticmethod
    def _format_drag_direction_timeframe(row: Any) -> str:
        if not isinstance(row, dict) or not str(row.get("direction", "") or ""):
            return "none"
        base = QuantResearchTeam._format_best_direction_timeframe(row)
        share = float(row.get("drag_share_of_negative_loss", 0.0) or 0.0)
        return f"{base}, drag share {share:.1%}"

    @staticmethod
    def _format_drag_direction_timeframe_rows(rows: Any) -> str:
        if not isinstance(rows, list) or not rows:
            return "none"
        formatted = [
            QuantResearchTeam._format_drag_direction_timeframe(row)
            for row in rows
            if isinstance(row, dict)
        ]
        filtered = [item for item in formatted if item != "none"]
        return "; ".join(filtered) if filtered else "none"

    @staticmethod
    def _format_exclusion_rescue_rows(rows: Any) -> str:
        if not isinstance(rows, list) or not rows:
            return "none"
        formatted: List[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label", "unknown") or "unknown")
            removed_count = int(row.get("removed_count", 0) or 0)
            removed_pnl = float(row.get("removed_pnl", 0.0) or 0.0)
            residual_pnl = float(row.get("residual_pnl", 0.0) or 0.0)
            formatted.append(
                f"{label}: removed {removed_count} trades / ${removed_pnl:+.2f}, residual ${residual_pnl:+.2f}"
            )
        return "; ".join(formatted) if formatted else "none"

    @staticmethod
    def _format_expiry_cap_label(value: Any) -> str:
        if value is None:
            return "uncapped"
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        if number.is_integer():
            return f"<={int(number)}h"
        return f"<={number:g}h"

    @staticmethod
    def _format_expiry_policy_row(row: Any) -> str:
        if not isinstance(row, dict) or not row:
            return "none"
        cap_label = str(row.get("cap_label") or QuantResearchTeam._format_expiry_cap_label(row.get("max_expiry_hours")))
        pnl = QuantResearchTeam._safe_float(row.get("total_pnl"), 0.0)
        filtered_trades = int(row.get("filtered_trades", 0) or 0)
        replay_accepted = bool(row.get("replay_accepted", False))
        return f"{cap_label} {pnl:+.2f} ({filtered_trades} trades, replay={replay_accepted})"

    @staticmethod
    def _format_expiry_policy_rows(rows: Any) -> str:
        if not isinstance(rows, list) or not rows:
            return "none"
        formatted: List[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            formatted.append(QuantResearchTeam._format_expiry_policy_row(row))
        return "; ".join(formatted) if formatted else "none"

    @staticmethod
    def _format_expiry_policy_delta(row: Any) -> str:
        if not isinstance(row, dict) or not row:
            return "none"
        pnl_delta = QuantResearchTeam._safe_float(row.get("pnl_delta"), 0.0)
        filtered_trade_delta = int(row.get("filtered_trade_delta", 0) or 0)
        score_delta = QuantResearchTeam._safe_float(row.get("score_delta"), 0.0)
        return f"{pnl_delta:+.2f} PnL / {filtered_trade_delta:+d} trades / {score_delta:+.2f} score"

    @staticmethod
    def _format_expiry_policy_verdict(row: Any) -> str:
        if not isinstance(row, dict) or not row:
            return "none"
        status = str(row.get("status", "unknown"))
        sampled_cap = str(row.get("sampled_research_cap_label", "none"))
        exploratory_cap = str(row.get("exploratory_cap_label", "none"))
        reasons = row.get("reason_codes", [])
        return (
            f"{status}; sampled={sampled_cap}; exploratory={exploratory_cap}; "
            f"reasons={reasons}"
        )

    @staticmethod
    def _format_runtime_provider_verdict(row: Any) -> str:
        if not isinstance(row, dict) or not row:
            return "none"
        status = str(row.get("status", "unknown"))
        healthy_provider_set = str(row.get("healthy_provider_set", "none"))
        reasons = row.get("reason_codes", [])
        return f"{status}; healthy_set={healthy_provider_set}; reasons={reasons}"

    @staticmethod
    def _format_runtime_cycle_interpretation(row: Any) -> str:
        if not isinstance(row, dict) or not row:
            return "none"
        status = str(row.get("status", "unknown"))
        reasons = row.get("reason_codes", [])
        return f"{status}; reasons={reasons}"

    @staticmethod
    def _format_current_runtime_blocker(row: Any) -> str:
        if not isinstance(row, dict):
            return "unknown"
        latest_scan = row.get("latest_runtime_scan_summary", {})
        if (
            isinstance(latest_scan, dict)
            and str(latest_scan.get("status", "") or "") == "NO_TRADEABLE_MARKETS_IN_LATEST_RUNTIME_SCAN"
        ):
            return QuantResearchTeam._format_runtime_scan_summary(latest_scan)
        latest_cycle = row.get("latest_cycle_interpretation", {})
        if isinstance(latest_cycle, dict) and latest_cycle:
            return QuantResearchTeam._format_runtime_cycle_interpretation(latest_cycle)
        provider = row.get("runtime_provider_verdict", {})
        return QuantResearchTeam._format_runtime_provider_verdict(provider)

    @staticmethod
    def _format_runtime_regime_snapshot(row: Any) -> str:
        if not isinstance(row, dict) or not row:
            return "none"
        status = str(row.get("status", "unknown") or "unknown")
        latest = str(row.get("latest_blocker", "none") or "none")
        chronic = str(row.get("chronic_blocker", "none") or "none")
        recent_mix = QuantResearchTeam._format_runtime_primary_cause_counts(row.get("recent_primary_cause_counts", {}))
        runtime_dirs = int(row.get("recent_runtime_dirs_considered", 0) or 0)
        prediction_runs = int(row.get("recent_prediction_runs_considered", 0) or 0)
        return (
            f"{status}; latest={latest}; chronic={chronic}; "
            f"recent_mix={recent_mix}; dirs={runtime_dirs}; prediction_runs={prediction_runs}"
        )

    @staticmethod
    def _format_runtime_primary_cause_counts(row: Any) -> str:
        if not isinstance(row, dict) or not row:
            return "none"
        parts: List[str] = []
        for key, value in sorted(row.items(), key=lambda item: (-int(item[1] or 0), str(item[0]))):
            count = int(value or 0)
            if count <= 0:
                continue
            parts.append(f"{str(key)}:{count}")
        return "; ".join(parts) if parts else "none"

    @staticmethod
    def _format_risk_timeframe(row: Any) -> str:
        if not isinstance(row, dict) or not row:
            return "none"
        timeframe = str(row.get("timeframe", "unknown"))
        pnl = QuantResearchTeam._safe_float(row.get("pnl"), 0.0)
        count = int(row.get("count", 0) or 0)
        return f"{timeframe} {pnl:+.2f} ({count} trades)"

    @staticmethod
    def _format_symbol_lane(row: Any) -> str:
        if not isinstance(row, dict) or not row:
            return "none"
        label = str(row.get("label") or row.get("variant") or "lane")
        pnl = QuantResearchTeam._safe_float(row.get("total_pnl") or row.get("pnl"), 0.0)
        filtered_trades = int(row.get("filtered_trades", row.get("count", 0)) or 0)
        replay_accepted = bool(row.get("replay_accepted", False))
        holdout_trades = int(row.get("holdout_trades", 0) or 0)
        return (
            f"{label} {pnl:+.2f} "
            f"({filtered_trades} trades, replay={replay_accepted}, holdout={holdout_trades})"
        )

    @staticmethod
    def _top_count_rows(rows: Any, total_override: Optional[int] = None, limit: int = 3) -> List[Dict[str, Any]]:
        if not isinstance(rows, dict):
            return []
        cleaned: List[tuple[str, int]] = []
        for key, value in rows.items():
            try:
                count = int(value or 0)
            except (TypeError, ValueError):
                continue
            if count <= 0:
                continue
            cleaned.append((str(key), count))
        cleaned.sort(key=lambda item: (-item[1], item[0]))
        total = int(total_override) if total_override is not None else sum(item[1] for item in cleaned)
        result: List[Dict[str, Any]] = []
        for key, count in cleaned[:limit]:
            share = (count / total) if total > 0 else None
            result.append(
                {
                    "key": key,
                    "count": count,
                    "share": round(share, 3) if share is not None else None,
                }
            )
        return result

    @staticmethod
    def _format_count_rows(rows: Any) -> str:
        if not isinstance(rows, list) or not rows:
            return "none"
        formatted: List[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = str(row.get("key", "unknown"))
            count = int(row.get("count", 0) or 0)
            share = row.get("share")
            if isinstance(share, (int, float)):
                formatted.append(f"{key} {count} ({share:.1%})")
            else:
                formatted.append(f"{key} {count}")
        return "; ".join(formatted) if formatted else "none"

    @staticmethod
    def _format_inventory_mix(key: Any, share: Any) -> str:
        if not key:
            return "none"
        if isinstance(share, (int, float)):
            return f"{key} ({share:.1%})"
        return str(key)

    @staticmethod
    def _format_optional_percent(value: Any) -> str:
        if not isinstance(value, (int, float)):
            return "none"
        return f"{value:.1%}"

    @staticmethod
    def _format_optional_ratio(value: Any) -> str:
        if not isinstance(value, (int, float)):
            return "none"
        return f"{value:.2f}x"

    @staticmethod
    def _format_optional_hours(value: Any) -> str:
        if not isinstance(value, (int, float)):
            return "none"
        return f"{float(value):.2f}h"

    @staticmethod
    def _sum_symbol_expiry_counts(rows: Any, symbol: str, buckets: set[str]) -> int:
        if not isinstance(rows, dict):
            return 0
        symbol_rows = rows.get(symbol, {})
        if not isinstance(symbol_rows, dict):
            return 0
        total = 0
        for bucket in buckets:
            try:
                total += int(symbol_rows.get(bucket, 0) or 0)
            except (TypeError, ValueError):
                continue
        return total

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed == parsed else default


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the Polymarket ETH/BTC research-team edge report"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help="Override Polymarket trader data directory",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Write reports to this directory instead of <data_dir>/research_team",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Override search symbols for the report scan",
    )
    parser.add_argument(
        "--strict-inventory-timeout",
        type=int,
        default=120,
        help="Seconds to wait for the strict inventory scan before writing a timeout",
    )
    parser.add_argument(
        "--broad-inventory-timeout",
        type=int,
        default=180,
        help="Seconds to wait for the broad inventory scan before writing a timeout",
    )
    parser.add_argument(
        "--skip-inventory",
        action="store_true",
        help="Skip live inventory scans and refresh only edge/performance artifacts",
    )
    args = parser.parse_args()

    kwargs: Dict[str, Any] = {}
    if args.data_dir:
        kwargs["_data_dir_override"] = Path(args.data_dir)
    if args.symbols:
        kwargs["search_symbols"] = [str(symbol).upper() for symbol in args.symbols if str(symbol).strip()]

    config = get_polymarket_cli_config(**kwargs) if kwargs else get_config()
    team = QuantResearchTeam(
        config=config,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        strict_inventory_timeout_seconds=args.strict_inventory_timeout,
        broad_inventory_timeout_seconds=args.broad_inventory_timeout,
        skip_inventory=args.skip_inventory,
    )
    report = team.run()

    edge_summary = report.get("edge_snapshot", {}).get("summary", {})
    perf = report.get("performance_summary", {})
    cprint("Polymarket quant research report written", "green")
    cprint(f"  Output Dir: {team.output_dir}", "white")
    cprint(f"  Best Variant: {edge_summary.get('best_variant_by_score', 'unknown')}", "white")
    cprint(f"  Supported Symbols: {edge_summary.get('supported_symbols', [])}", "white")
    cprint(f"  Closed Trades: {perf.get('closed_trades', 0)}", "white")
    cprint(f"  Total PnL: ${perf.get('total_pnl', 0.0):+.2f}", "white")


if __name__ == "__main__":
    main()
