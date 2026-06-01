"""
Polymarket CLI Orchestrator

Conservative cycle-based orchestrator for Polymarket trading.
Preserves existing execution interfaces while adding:
- deterministic per-cycle budget usage
- explicit execution ledger (planned/executed/skipped/blocked)
- richer per-cycle summaries for dashboards and audits
- optional status mode for health/safety checks
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from termcolor import cprint

from .cli_wrapper import PolymarketCLI
from .config import ExecutionMode, PolymarketCLIConfig, get_config
from .edge_calculator import CLIEdgeCalculator
from .market_scanner import CLIMarketScanner
from .models import CLIMarket, TradeDecision
from .risk_manager import RiskManager
from .swarm_analyzer import CLISwarmAnalyzer
from .trader import CLITrader
from .whale_tracker import WhaleTracker
from .arbitrage_detector import ArbitrageDetector
from .data_signals import ExchangeDataSignals
from .weather_candidate_ranker import WeatherCandidateRanker
from .weather_evidence_store import WeatherEvidenceStore
from .weather_gate import WeatherGate
from .weather_high_res_cycle import WeatherHighResolutionIngestCycleRunner
from .weather_live_eligibility import WeatherLiveEligibilityGate
from .weather_market_tape import WeatherMarketTapeCollector


class PolymarketCLIOrchestrator:
    """
    Main loop over discovery -> analysis -> execution.

    Public method signatures are kept stable for existing scripts:
    - execute_trade via CLITrader
    - run(cycles=..., status=...)
    - _total_trades attribute for external reporters
    """

    def __init__(self, config: Optional[PolymarketCLIConfig] = None):
        self.config = config or get_config()
        if (
            str(getattr(self.config, "market_vertical", "crypto") or "crypto").lower() == "weather"
            and bool(getattr(self.config, "weather_auto_ingest_high_resolution", False))
            and not str(getattr(self.config, "weather_high_resolution_cache_dir", "") or "").strip()
        ):
            self.config.weather_high_resolution_cache_dir = str(
                (self.config.data_dir / "weather_high_resolution_cache").expanduser().resolve()
            )
        self.cli = PolymarketCLI(self.config)
        self.scanner = CLIMarketScanner(self.config, self.cli)
        self.analyzer = CLISwarmAnalyzer(self.config)
        self.edge_calculator = CLIEdgeCalculator(self.config)
        self.arbitrage_detector = ArbitrageDetector(self.config)
        self.risk_manager = RiskManager(self.config)
        self.trader = CLITrader(self.config, self.cli, self.risk_manager)
        self.whale_tracker = WhaleTracker(self.config, self.cli)
        self.signals = ExchangeDataSignals(self.config)
        self.weather_candidate_ranker = WeatherCandidateRanker(self.config)
        self.weather_gate = WeatherGate(self.config)
        self.weather_market_tape = WeatherMarketTapeCollector(self.config, self.cli)
        self.weather_evidence_store = WeatherEvidenceStore(self.config)
        self._weather_high_res_cycle_runner: Optional[WeatherHighResolutionIngestCycleRunner] = None
        self._cycle_counter = 0
        self._total_trades = 0
        self._total_rejections = 0
        self._total_cycles = 0
        self._last_cycle_summary: Dict[str, Any] = {}
        self._weather_gate_events: List[Dict[str, Any]] = []
        self._last_weather_gate_verdict: Dict[str, Any] = {}
        self._last_weather_candidate: Dict[str, Any] = {}

        self.config.ensure_dirs()

    @property
    def total_trades(self) -> int:
        return self._total_trades

    def get_run_status(self) -> Dict[str, Any]:
        """
        Health/status snapshot suitable for dashboards and status scripts.
        """
        risk_summary = self.risk_manager.get_risk_summary()
        health = self.cli.get_health_status()
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "execution_mode": self.config.execution_mode.value,
            "cycle": self._cycle_counter,
            "cycles_completed": self._total_cycles,
            "trades_executed": self._total_trades,
            "rejections": self._total_rejections,
            "total_positions": risk_summary.get("positions", 0),
            "total_exposure": risk_summary.get("total_exposure", 0.0),
            "risk_status": risk_summary,
            "cli_status": health,
            "paper_balance": self.trader.get_paper_balance(),
            "config": {
                "max_total_exposure_usd": self.config.max_total_exposure_usd,
                "max_position_usd": self.config.max_position_usd,
                "min_position_usd": self.config.min_position_usd,
                "cycle_interval_seconds": self.config.cycle_interval_seconds,
                "max_markets_to_analyze": self.config.max_markets_to_analyze,
            },
        }

    def run(self, cycles: int = 0, status: bool = False):
        """
        Run orchestration loop.

        cycles=0 => run until interrupted.
        status=True => print and return status only.
        """
        if status:
            status_payload = self.get_run_status()
            cprint("Status:", "cyan")
            cprint(json.dumps(status_payload, indent=2), "white")
            return status_payload

        start_message = "running continuously" if cycles in (0, None) else f"{cycles} cycles"
        cprint(f"Starting Orchestrator ({start_message})", "yellow")
        cprint(
            f"Mode={self.config.execution_mode.value}, Markets/cycle={self.config.max_markets_to_analyze}, "
            f"MaxExposure=${self.config.max_total_exposure_usd:.2f}",
            "white",
        )

        run_summaries: List[Dict[str, Any]] = []
        try:
            while True:
                self._cycle_counter += 1
                summary = self._run_cycle(self._cycle_counter)
                run_summaries.append(summary)
                self._last_cycle_summary = summary
                self._total_cycles += 1

                if cycles and self._cycle_counter >= cycles:
                    break

                if self.config.cycle_interval_seconds > 0:
                    time.sleep(self.config.cycle_interval_seconds)
        except KeyboardInterrupt:
            cprint("\nCycle run interrupted by user", "yellow")

        return run_summaries

    def _run_cycle(self, cycle_number: int) -> Dict[str, Any]:
        started_at = time.perf_counter()
        now = datetime.utcnow()
        cycle_start = now.isoformat()
        cycle_summary: Dict[str, Any] = {
            "cycle": cycle_number,
            "started_at": cycle_start,
            "execution_mode": self.config.execution_mode.value,
            "budget_before_usd": round(max(0.0, self.config.max_total_exposure_usd - self.risk_manager.total_exposure), 2),
            "current_phase": "cycle",
            "current_phase_status": "started",
            "phase_progress": [],
            "planned": [],
            "executed": [],
            "skipped": [],
            "blocked": [],
            "resolved_markets": [],
            "close_results": [],
            "whale_signals": [],
            "rejections": [],
            "fill_outcomes": [],
            "cycle_errors": [],
            "swarm_runtime": {
                "markets_analyzed": 0,
                "runtime_ready_predictions": 0,
                "degraded_swarm_predictions": 0,
                "single_model_control_predictions": 0,
                "measurement_boundary_counts": {},
                "analysis_cohort_counts": {},
                "abstain_reason_counts": {},
            },
        }
        weather_market_tape_snapshots: List[Any] = []
        weather_market_tape_capture_error = ""
        weather_feature_captured_at = ""

        try:
            self._update_cycle_progress(cycle_summary, "cycle", "started")
            try:
                phase_started = time.perf_counter()
                self._update_cycle_progress(cycle_summary, "reconcile_live_orders", "started")
                live_order_events = self.risk_manager.reconcile_live_orders(self.cli)
                if live_order_events:
                    cycle_summary["live_order_events"] = live_order_events
                self._update_cycle_progress(
                    cycle_summary,
                    "reconcile_live_orders",
                    "completed",
                    phase_started=phase_started,
                    details={"events": len(live_order_events or [])},
                )
            except Exception as exc:
                cycle_summary["cycle_errors"].append(
                    {
                        "phase": "reconcile_live_orders",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                self._update_cycle_progress(
                    cycle_summary,
                    "reconcile_live_orders",
                    "failed",
                    phase_started=phase_started,
                    error=f"{type(exc).__name__}: {exc}",
                )

            phase_started = time.perf_counter()
            self._update_cycle_progress(cycle_summary, "risk_check", "started")
            self.risk_manager.check_circuit_breakers()
            risk_before = self.risk_manager.get_risk_summary()
            cycle_summary["risk_status_before"] = risk_before
            cycle_summary["cycle_errors"].append(
                {
                    "phase": "risk_check",
                    "status": "ok",
                }
            )
            self._update_cycle_progress(cycle_summary, "risk_check", "completed", phase_started=phase_started)

            # Keep open positions prices fresh.
            try:
                phase_started = time.perf_counter()
                self._update_cycle_progress(cycle_summary, "refresh_position_prices", "started")
                updated_positions = self.risk_manager.refresh_position_prices(self.cli)
                if updated_positions:
                    cycle_summary["position_price_updates"] = updated_positions
                self._update_cycle_progress(
                    cycle_summary,
                    "refresh_position_prices",
                    "completed",
                    phase_started=phase_started,
                    details={"updated_positions": len(updated_positions or {})},
                )
            except Exception as exc:
                cycle_summary["cycle_errors"].append(
                    {
                        "phase": "refresh_position_prices",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                self._update_cycle_progress(
                    cycle_summary,
                    "refresh_position_prices",
                    "failed",
                    phase_started=phase_started,
                    error=f"{type(exc).__name__}: {exc}",
                )

            # Resolve and close stale positions.
            resolved_markets = []
            try:
                phase_started = time.perf_counter()
                self._update_cycle_progress(cycle_summary, "check_resolved_markets", "started")
                resolved_markets = self.risk_manager.check_resolved_markets(self.cli)
                self._update_cycle_progress(
                    cycle_summary,
                    "check_resolved_markets",
                    "completed",
                    phase_started=phase_started,
                    details={"resolved_markets": len(resolved_markets or [])},
                )
            except Exception as exc:
                cycle_summary["cycle_errors"].append(
                    {
                        "phase": "check_resolved_markets",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                self._update_cycle_progress(
                    cycle_summary,
                    "check_resolved_markets",
                    "failed",
                    phase_started=phase_started,
                    error=f"{type(exc).__name__}: {exc}",
                )
            if resolved_markets:
                cycle_summary["resolved_markets"] = resolved_markets
                cycle_summary["resolution_source_errors"] = [
                    {
                        "market_id": item.get("market_id"),
                        "source": item.get("resolution_source") or item.get("resolution_note"),
                    }
                    for item in resolved_markets
                    if isinstance(item, dict)
                ]

            # Exit signals from existing risk policy.
            phase_started = time.perf_counter()
            self._update_cycle_progress(cycle_summary, "close_positions", "started")
            exit_market_ids = self.risk_manager.check_exit_signals()
            close_results = []
            for market_id in exit_market_ids:
                pos = self.risk_manager.positions.get(market_id)
                if not pos:
                    continue
                close_price = float(getattr(pos, "current_price", 0.0) or 0.0)
                pnl = self.trader.close_position(market_id, close_price, reason="exit_signal")
                close_results.append(
                    {
                        "market_id": market_id,
                        "question": getattr(pos, "question", ""),
                        "pnl": pnl if pnl is not None else 0.0,
                        "status": "closed" if pnl is not None else "close_failed",
                        "close_price": close_price,
                    }
                )
            if close_results:
                cycle_summary["close_results"] = close_results
            self._update_cycle_progress(
                cycle_summary,
                "close_positions",
                "completed",
                phase_started=phase_started,
                details={"closed_positions": len(close_results)},
            )

            # Optional whale scan (interval-based throttle).
            if self._should_scan_whales():
                try:
                    phase_started = time.perf_counter()
                    self._update_cycle_progress(cycle_summary, "scan_whales", "started")
                    whale_changes = self.whale_tracker.scan_whales()
                    cycle_summary["whale_signals"] = whale_changes
                    self._update_cycle_progress(
                        cycle_summary,
                        "scan_whales",
                        "completed",
                        phase_started=phase_started,
                        details={"whale_signals": len(whale_changes or [])},
                    )
                except Exception as exc:
                    cycle_summary["cycle_errors"].append(
                        {
                            "phase": "scan_whales",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    self._update_cycle_progress(
                        cycle_summary,
                        "scan_whales",
                        "failed",
                        phase_started=phase_started,
                        error=f"{type(exc).__name__}: {exc}",
                    )

            phase_started = time.perf_counter()
            self._update_cycle_progress(cycle_summary, "market_scan", "started")
            scan_ok, raw_markets = self._run_cycle_stage(
                "market_scan",
                lambda: self.scanner.scan_markets(force_refresh=False),
            )
            if not scan_ok:
                self._update_cycle_progress(
                    cycle_summary,
                    "market_scan",
                    "failed",
                    phase_started=phase_started,
                    error=str(raw_markets),
                )
                cycle_summary["status"] = "failed"
                cycle_summary["error"] = str(raw_markets)
                cycle_summary["budget_after_usd"] = cycle_summary["budget_before_usd"]
                cycle_summary["duration_seconds"] = round(time.perf_counter() - started_at, 3)
                self._append_run_log_line(cycle_summary)
                self._record_cycle_summary(cycle_summary)
                self._print_cycle_summary(cycle_summary)
                return cycle_summary

            scan_telemetry = getattr(self.scanner, "last_scan_telemetry", {})
            if isinstance(scan_telemetry, dict) and scan_telemetry:
                cycle_summary["scanner_telemetry"] = scan_telemetry

            cycle_summary["markets_found"] = len(raw_markets)
            self._update_cycle_progress(
                cycle_summary,
                "market_scan",
                "completed",
                phase_started=phase_started,
                details={"markets_found": len(raw_markets)},
            )

            ranked = self.scanner.rank_markets(raw_markets)
            ranked = ranked[: self.config.max_markets_to_analyze]
            cycle_summary["markets_ranked"] = len(ranked)
            top_markets = [m for m, _ in ranked]
            cycle_summary["markets_selected"] = [m.condition_id for m in top_markets]

            if not top_markets:
                cycle_summary["status"] = "no_markets"
                cycle_summary["budget_after_usd"] = cycle_summary["budget_before_usd"]
                cycle_summary["duration_seconds"] = round(time.perf_counter() - started_at, 3)
                self._append_run_log_line(cycle_summary)
                self._record_cycle_summary(cycle_summary)
                self._print_cycle_summary(cycle_summary)
                return cycle_summary

            if self._is_weather_vertical() and bool(getattr(self.config, "weather_evidence_enabled", True)):
                try:
                    phase_started = time.perf_counter()
                    self._update_cycle_progress(cycle_summary, "weather_market_tape", "started")
                    weather_market_tape_snapshots = self.weather_market_tape.snapshot_markets(top_markets)
                    cycle_summary["weather_market_tape"] = {
                        "status": "captured",
                        "snapshots": len(weather_market_tape_snapshots),
                    }
                    self._update_cycle_progress(
                        cycle_summary,
                        "weather_market_tape",
                        "completed",
                        phase_started=phase_started,
                        details=cycle_summary["weather_market_tape"],
                    )
                except Exception as exc:
                    weather_market_tape_capture_error = f"{type(exc).__name__}: {exc}"
                    cycle_summary["cycle_errors"].append(
                        {
                            "phase": "weather_market_tape",
                            "error": weather_market_tape_capture_error,
                        }
                    )
                    self._update_cycle_progress(
                        cycle_summary,
                        "weather_market_tape",
                        "failed",
                        phase_started=phase_started,
                        error=weather_market_tape_capture_error,
                    )

            if self._is_weather_vertical() and bool(
                getattr(self.config, "weather_auto_ingest_high_resolution", False)
            ):
                try:
                    phase_started = time.perf_counter()
                    self._update_cycle_progress(cycle_summary, "weather_high_resolution_ingest", "started")
                    ingest_report = self._weather_high_resolution_ingest_runner().run(
                        top_markets,
                        dry_run=False,
                        force=False,
                    )
                    cycle_summary["weather_high_resolution_ingest"] = ingest_report.summary()
                    self._update_cycle_progress(
                        cycle_summary,
                        "weather_high_resolution_ingest",
                        ingest_report.status,
                        phase_started=phase_started,
                        details=ingest_report.summary(),
                    )
                except Exception as exc:
                    cycle_summary["cycle_errors"].append(
                        {
                            "phase": "weather_high_resolution_ingest",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    self._update_cycle_progress(
                        cycle_summary,
                        "weather_high_resolution_ingest",
                        "failed",
                        phase_started=phase_started,
                        error=f"{type(exc).__name__}: {exc}",
                    )

            symbols = self._collect_symbols(top_markets)
            try:
                phase_started = time.perf_counter()
                signal_phase = "weather_signals" if self._is_weather_vertical() else "exchange_signals"
                self._update_cycle_progress(cycle_summary, signal_phase, "started")
                if self._is_weather_vertical() and hasattr(self.signals, "get_market_context"):
                    if hasattr(self.signals, "set_market_tape_snapshots"):
                        self.signals.set_market_tape_snapshots(weather_market_tape_snapshots)
                    price_context = self.signals.get_market_context(top_markets)
                    weather_feature_captured_at = datetime.utcnow().isoformat()
                else:
                    price_context = self.signals.get_signals(symbols)
                self._update_cycle_progress(
                    cycle_summary,
                    signal_phase,
                    "completed",
                    phase_started=phase_started,
                    details={
                        "symbols": symbols,
                        "contexts": len(price_context or {}),
                    },
                )
            except Exception as exc:
                cycle_summary["cycle_errors"].append(
                    {
                        "phase": "weather_signals" if self._is_weather_vertical() else "exchange_signals",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                price_context = {}
                self._update_cycle_progress(
                    cycle_summary,
                    "weather_signals" if self._is_weather_vertical() else "exchange_signals",
                    "failed",
                    phase_started=phase_started,
                    error=f"{type(exc).__name__}: {exc}",
                )

            candidate_decisions: List[Tuple[TradeDecision, CLIMarket, str]] = []
            self._weather_gate_events = []
            portfolio_positions = [p.to_dict() for p in self.risk_manager.positions.values()]

            phase_started = time.perf_counter()
            self._update_cycle_progress(cycle_summary, "swarm_analysis", "started")
            for market, _score in ranked:
                decision = self._build_swarm_decision(
                    market=market,
                    price_context=price_context,
                    portfolio_positions=portfolio_positions,
                )
                self._record_swarm_runtime(cycle_summary)
                if decision is not None:
                    candidate_decisions.append((decision, market, "swarm"))
            self._update_cycle_progress(
                cycle_summary,
                "swarm_analysis",
                "completed",
                phase_started=phase_started,
                details={"candidates": len(candidate_decisions)},
            )
            if self._is_weather_vertical():
                cycle_summary["weather_gate_events"] = list(self._weather_gate_events)
                cycle_summary["weather_candidate_count"] = len(self._weather_gate_events)
                cycle_summary["weather_gate_blocked"] = len(
                    [event for event in self._weather_gate_events if not event.get("accepted")]
                )

            try:
                phase_started = time.perf_counter()
                self._update_cycle_progress(cycle_summary, "detect_arbitrage", "started")
                arb_markets = raw_markets if self._is_weather_vertical() else top_markets
                opportunities = self.arbitrage_detector.detect_all(arb_markets)
                self._update_cycle_progress(
                    cycle_summary,
                    "detect_arbitrage",
                    "completed",
                    phase_started=phase_started,
                    details={
                        "opportunities": len(opportunities or []),
                        "markets_scanned": len(arb_markets),
                    },
                )
            except Exception as exc:
                cycle_summary["cycle_errors"].append(
                    {
                        "phase": "detect_arbitrage",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                opportunities = []
                self._update_cycle_progress(
                    cycle_summary,
                    "detect_arbitrage",
                    "failed",
                    phase_started=phase_started,
                    error=f"{type(exc).__name__}: {exc}",
                )
            arb_decisions = self._build_arbitrage_decisions(
                raw_markets if self._is_weather_vertical() else top_markets,
                opportunities,
            )
            candidate_decisions.extend(arb_decisions)

            cycle_summary["swarm_candidates"] = len([1 for _, _, src in candidate_decisions if src == "swarm"])
            cycle_summary["arb_candidates"] = len([1 for _, _, src in candidate_decisions if src == "arbitrage"])
            cycle_summary["candidate_count"] = len(candidate_decisions)

            phase_started = time.perf_counter()
            self._update_cycle_progress(cycle_summary, "execute_plan", "started")
            ledger = self._execute_cycle_plan(candidate_decisions, cycle_summary)
            cycle_summary["planned"].extend(ledger["planned"])
            cycle_summary["executed"].extend(ledger["executed"])
            cycle_summary["skipped"].extend(ledger["skipped"])
            cycle_summary["blocked"].extend(ledger["blocked"])
            cycle_summary["rejections"] = ledger["rejections"]
            cycle_summary["fill_outcomes"] = ledger["fill_outcomes"]
            self._update_cycle_progress(
                cycle_summary,
                "execute_plan",
                "completed",
                phase_started=phase_started,
                details={
                    "executed": len(ledger["executed"]),
                    "blocked": len(ledger["blocked"]),
                    "skipped": len(ledger["skipped"]),
                },
            )

            cycle_summary["status"] = "complete"
            if risk_before.get("halted"):
                cycle_summary["status"] = "halted"

            cycle_summary["trades_executed"] = len(ledger["executed"])
            cycle_summary["trades_planned"] = len(ledger["planned"])
            cycle_summary["trades_skipped"] = len(ledger["skipped"])
            cycle_summary["trades_blocked"] = len(ledger["blocked"])
            cycle_summary["budget_after_usd"] = round(
                max(0.0, self.config.max_total_exposure_usd - self.risk_manager.total_exposure),
                2,
            )
            cycle_summary["risk_status_after"] = self.risk_manager.get_risk_summary()
            cycle_summary["paper_balance"] = self.trader.get_paper_balance()
            if self._is_weather_vertical():
                cycle_summary["weather_evidence"] = self._record_weather_evidence(
                    top_markets=top_markets,
                    price_context=price_context,
                    cycle_summary=cycle_summary,
                    tape_snapshots=weather_market_tape_snapshots,
                    market_tape_error=weather_market_tape_capture_error,
                    feature_captured_at=weather_feature_captured_at,
                )
            cycle_summary["duration_seconds"] = round(time.perf_counter() - started_at, 3)
            self._update_cycle_progress(
                cycle_summary,
                "cycle",
                cycle_summary["status"],
                phase_started=started_at,
            )
            self._append_run_log_line(cycle_summary)
            self._record_cycle_summary(cycle_summary)
            self._print_cycle_summary(cycle_summary)
            return cycle_summary
        except Exception as exc:
            cycle_summary["status"] = "failed"
            cycle_summary["error"] = str(exc)
            cycle_summary["budget_after_usd"] = round(
                max(0.0, self.config.max_total_exposure_usd - self.risk_manager.total_exposure),
                2,
            )
            cycle_summary["duration_seconds"] = round(time.perf_counter() - started_at, 3)
            self._update_cycle_progress(
                cycle_summary,
                cycle_summary.get("current_phase", "cycle"),
                "failed",
                phase_started=started_at,
                error=str(exc),
            )
            self._append_run_log_line(cycle_summary)
            self._record_cycle_summary(cycle_summary)
            cprint(f"Cycle {cycle_number} failed: {exc}", "red")
            return cycle_summary

    def _run_cycle_stage(self, phase: str, fn) -> Tuple[bool, Any]:
        retries = max(0, int(self.config.cli_retry_count))
        max_attempts = retries + 1
        last_error: Optional[Exception] = None

        for attempt in range(max_attempts):
            try:
                return True, fn()
            except Exception as exc:
                last_error = exc
                if attempt < max_attempts - 1:
                    delay = max(0.0, float(self.config.cli_retry_backoff_seconds))
                    if delay > 0:
                        time.sleep(delay * (attempt + 1))
                    continue

        return False, f"{phase} failed: {type(last_error).__name__}: {last_error}"

    def _should_scan_whales(self) -> bool:
        interval = max(1, int(getattr(self.config, "whale_scan_interval_cycles", 6)))
        return (self._cycle_counter % interval) == 0

    def _collect_symbols(self, markets: List[CLIMarket]) -> List[str]:
        symbols = []
        seen = set()
        for market in markets:
            sym = self._safe_symbol(getattr(market, "symbol", ""))
            if sym and sym not in seen:
                seen.add(sym)
                symbols.append(sym)
        return symbols

    def _safe_symbol(self, value: str) -> str:
        if not value:
            return ""
        return str(value).strip().upper()

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _is_weather_vertical(self) -> bool:
        return str(getattr(self.config, "market_vertical", "crypto") or "crypto").lower() == "weather"

    def _weather_high_resolution_ingest_runner(self) -> WeatherHighResolutionIngestCycleRunner:
        if self._weather_high_res_cycle_runner is None:
            self._weather_high_res_cycle_runner = WeatherHighResolutionIngestCycleRunner(
                self.config,
                cache_dir=getattr(self.config, "weather_high_resolution_cache_dir", "") or None,
        )
        return self._weather_high_res_cycle_runner

    def _record_weather_evidence(
        self,
        *,
        top_markets: List[CLIMarket],
        price_context: Dict[str, Any],
        cycle_summary: Dict[str, Any],
        tape_snapshots: Optional[List[Any]] = None,
        market_tape_error: str = "",
        feature_captured_at: str = "",
    ) -> Dict[str, Any]:
        if not bool(getattr(self.config, "weather_evidence_enabled", True)):
            return {"status": "disabled"}
        try:
            cycle = int(cycle_summary.get("cycle", 0) or 0)
            errors = []
            if market_tape_error:
                errors.append(f"weather_market_tape_capture_failed:{market_tape_error}")
            tape_snapshots = list(tape_snapshots or [])
            market_tape_count = self.weather_evidence_store.append_market_tape(
                tape_snapshots,
                cycle=cycle,
            )
            feature_count = self.weather_evidence_store.append_feature_snapshots(
                top_markets,
                price_context,
                cycle=cycle,
                captured_at=feature_captured_at or None,
            )
            candidate_events = self._weather_evidence_candidate_events(cycle_summary)
            candidate_count = self.weather_evidence_store.append_candidate_events(
                candidate_events,
                cycle=cycle,
            )
            return {
                "status": "recorded_with_errors" if errors else "recorded",
                "market_tape_count": market_tape_count,
                "feature_snapshot_count": feature_count,
                "candidate_event_count": candidate_count,
                "root_dir": str(self.weather_evidence_store.root_dir),
                "errors": errors,
            }
        except Exception as exc:
            return {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "root_dir": str(self.weather_evidence_store.root_dir),
            }

    def _weather_evidence_candidate_events(self, cycle_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
        status_by_market: Dict[str, Dict[str, Any]] = {}
        precedence = {"planned": 1, "skipped": 2, "blocked": 3, "executed": 4}
        for status_name in ("planned", "skipped", "blocked", "executed"):
            for item in cycle_summary.get(status_name, []) or []:
                if not isinstance(item, dict):
                    continue
                market_id = str(item.get("market_id") or "")
                if not market_id:
                    continue
                existing = status_by_market.get(market_id, {})
                if precedence.get(status_name, 0) < precedence.get(str(existing.get("final_trade_status", "")), 0):
                    continue
                status_by_market[market_id] = {
                    "final_trade_status": status_name,
                    "final_trade_record": item,
                    "final_trade_side": item.get("side"),
                    "final_trade_price": item.get("price"),
                    "final_trade_size_usd": item.get("size_usd", item.get("requested", item.get("executed_size"))),
                }

        events: List[Dict[str, Any]] = []
        for event in self._weather_gate_events:
            if not isinstance(event, dict):
                continue
            market_id = str(event.get("market_id") or "")
            enriched = dict(event)
            final_status = status_by_market.get(market_id, {})
            if final_status:
                enriched.update(final_status)
            elif enriched.get("accepted"):
                enriched["final_trade_status"] = "not_planned_after_gate"
            else:
                enriched["final_trade_status"] = "blocked_by_weather_gate"
            enriched.setdefault("source", "weather_gate")
            events.append(enriched)
        return events

    def _weather_context_for_market(self, market: CLIMarket, price_context: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(price_context, dict):
            return {}
        return dict(
            price_context.get(str(getattr(market, "condition_id", "")))
            or price_context.get(getattr(market, "condition_id", ""))
            or {}
        )

    def _weather_pretrade_gate(
        self,
        market: CLIMarket,
        price_context: Dict[str, Any],
    ) -> Tuple[bool, str]:
        context = self._weather_context_for_market(market, price_context)
        candidate = self.weather_candidate_ranker.build_candidate(market, context)
        verdict = self.weather_gate.evaluate(market, context, candidate)
        self._last_weather_candidate = candidate.to_dict()
        self._last_weather_gate_verdict = verdict.to_dict()
        return bool(verdict.accepted), str(verdict.reason)

    def _record_swarm_runtime(self, cycle_summary: Dict[str, Any]) -> None:
        runtime = cycle_summary.setdefault(
            "swarm_runtime",
            {
                "markets_analyzed": 0,
                "runtime_ready_predictions": 0,
                "degraded_swarm_predictions": 0,
                "single_model_control_predictions": 0,
                "measurement_boundary_counts": {},
                "analysis_cohort_counts": {},
                "abstain_reason_counts": {},
            },
        )
        runtime["markets_analyzed"] = int(runtime.get("markets_analyzed", 0) or 0) + 1

        metadata = dict(getattr(self.analyzer, "last_analysis_metadata", {}) or {})
        if not metadata:
            runtime["measurement_boundary_counts"]["unknown"] = (
                runtime["measurement_boundary_counts"].get("unknown", 0) + 1
            )
            return

        runtime_ready = bool(metadata.get("runtime_ready", False))
        measurement_boundary = str(metadata.get("measurement_boundary", "swarm") or "swarm")
        analysis_cohort = str(metadata.get("analysis_cohort", "swarm") or "swarm")
        abstain_reason = str(metadata.get("abstain_reason", "") or "").strip()

        if runtime_ready:
            runtime["runtime_ready_predictions"] = int(runtime.get("runtime_ready_predictions", 0) or 0) + 1
        if measurement_boundary == "degraded_swarm":
            runtime["degraded_swarm_predictions"] = int(runtime.get("degraded_swarm_predictions", 0) or 0) + 1
        if analysis_cohort == "single_model_control":
            runtime["single_model_control_predictions"] = int(runtime.get("single_model_control_predictions", 0) or 0) + 1

        runtime["measurement_boundary_counts"][measurement_boundary] = (
            runtime["measurement_boundary_counts"].get(measurement_boundary, 0) + 1
        )
        runtime["analysis_cohort_counts"][analysis_cohort] = (
            runtime["analysis_cohort_counts"].get(analysis_cohort, 0) + 1
        )
        if abstain_reason:
            runtime["abstain_reason_counts"][abstain_reason] = (
                runtime["abstain_reason_counts"].get(abstain_reason, 0) + 1
            )

    def _build_swarm_decision(
        self,
        market: CLIMarket,
        price_context: Dict[str, Any],
        portfolio_positions: List[Dict[str, Any]],
    ) -> Optional[TradeDecision]:
        timestamp = datetime.utcnow()
        if self._is_weather_vertical():
            gate_ok, gate_reason = self._weather_pretrade_gate(market, price_context)
            self._weather_gate_events.append(
                {
                    "market_id": str(getattr(market, "condition_id", "")),
                    "captured_at": timestamp.isoformat(),
                    "accepted": bool(gate_ok),
                    "reason": gate_reason,
                    "candidate": dict(self._last_weather_candidate or {}),
                    "verdict": dict(self._last_weather_gate_verdict or {}),
                }
            )
            if not gate_ok:
                cprint(f"Weather pretrade gate blocked {market.condition_id}: {gate_reason}", "yellow")
                return None
            ai_decision = self._weather_context_for_market(market, price_context).get("ai_decision", {})
            ai_trade = self._build_weather_ai_trade_decision(market, ai_decision, timestamp)
            if ai_trade is not None:
                return ai_trade
        try:
            consensus = self.analyzer.analyze_market(
                market,
                price_context=price_context,
                portfolio_positions=portfolio_positions,
            )
        except Exception as exc:
            cprint(f"Swarm analysis failed for {getattr(market, 'condition_id', '')}: {exc}", "yellow")
            return None

        if not consensus:
            return None

        if getattr(consensus, "consensus_prediction", "ABSTAIN") not in {"YES", "NO"}:
            return None

        edge = self.edge_calculator.calculate_edge(
            estimated_probability=float(getattr(consensus, "consensus_probability", 0.0) or 0.0),
            market_price=float(getattr(market, "yes_price", 0.0) or 0.0),
            confidence=float(getattr(consensus, "consensus_confidence", 0.0) or 0.0),
            hours_until_resolution=max(0.0, float(getattr(market, "time_remaining_hours", 0.0) or 0.0)),
            available_capital=self.config.max_total_exposure_usd,
        )

        if not self.edge_calculator.should_trade(edge):
            return None

        trade_price = (
            float(market.yes_price)
            if edge.recommended_side == "YES"
            else float(market.no_price)
        )
        if trade_price <= 0:
            trade_price = float(market.yes_price) if edge.recommended_side == "YES" else (1.0 - float(market.yes_price))

        return TradeDecision(
            market_id=str(getattr(market, "condition_id", "")),
            timestamp=timestamp,
            should_trade=True,
            side=str(edge.recommended_side).upper(),
            size_usd=float(edge.recommended_size_usd),
            price=float(trade_price),
            confidence=float(edge.confidence),
            reason=(
                f"Swarm edge={edge.edge_percent:.2f}% "
                f"prob={float(consensus.consensus_probability):.3f} "
                f"conf={float(consensus.consensus_confidence):.2f}"
            ),
            source="swarm",
            prediction_path=str(getattr(consensus, "analysis_path", "") or ""),
        )

    def _build_weather_ai_trade_decision(
        self,
        market: CLIMarket,
        ai_decision: Dict[str, Any],
        timestamp: datetime,
    ) -> Optional[TradeDecision]:
        if not isinstance(ai_decision, dict) or not ai_decision.get("usable_for_paper"):
            return None
        if str(getattr(self.config, "weather_ai_autonomy_mode", "paper_only") or "") != "paper_only":
            return None
        if self.config.execution_mode == ExecutionMode.LIVE:
            return None

        p_yes = self._safe_float(ai_decision.get("p_yes"))
        confidence = self._safe_float(ai_decision.get("confidence"))
        if p_yes is None or confidence is None:
            return None
        edge = self.edge_calculator.calculate_edge(
            estimated_probability=p_yes,
            market_price=float(getattr(market, "yes_price", 0.0) or 0.0),
            confidence=confidence,
            hours_until_resolution=max(0.0, float(getattr(market, "time_remaining_hours", 0.0) or 0.0)),
            available_capital=self.config.max_total_exposure_usd,
        )
        if not self.edge_calculator.should_trade(edge):
            return None

        ai_size = self._safe_float(ai_decision.get("recommended_size_usd"))
        size = float(edge.recommended_size_usd)
        if ai_size is not None and ai_size > 0:
            size = min(size, ai_size)
        if size <= 0:
            return None

        side = str(edge.recommended_side).upper()
        trade_price = float(getattr(market, "yes_price", 0.0) if side == "YES" else getattr(market, "no_price", 0.0))
        if trade_price <= 0:
            trade_price = float(getattr(market, "yes_price", 0.0) or 0.0) if side == "YES" else (
                1.0 - float(getattr(market, "yes_price", 0.0) or 0.0)
            )

        lane = str(ai_decision.get("strategy_lane") or "forecast_model").strip()
        provider = str(ai_decision.get("provider") or getattr(self.config, "weather_ai_lead_provider", "openai"))
        model_name = str(ai_decision.get("model_name") or getattr(self.config, "weather_ai_lead_model", "gpt-5.5"))
        thesis = str(ai_decision.get("trade_thesis") or "").strip()
        return TradeDecision(
            market_id=str(getattr(market, "condition_id", "")),
            timestamp=timestamp,
            should_trade=True,
            side=side,
            size_usd=float(size),
            price=float(trade_price),
            confidence=float(edge.confidence),
            reason=(
                f"Weather AI {lane} edge={edge.edge_percent:.2f}% "
                f"p_yes={p_yes:.3f} conf={confidence:.2f}"
                + (f" thesis={thesis[:120]}" if thesis else "")
            ),
            source="weather_ai_forecast",
            prediction_path=f"weather_ai|{provider}/{model_name}|{lane}",
        )

    def _build_arbitrage_decisions(
        self, markets: List[CLIMarket], opportunities: List
    ) -> List[Tuple[TradeDecision, CLIMarket, str]]:
        market_index = {m.condition_id: m for m in markets}
        decisions: List[Tuple[TradeDecision, CLIMarket, str]] = []

        for opp in opportunities:
            if float(getattr(opp, "edge_percent", 0.0)) < float(self.config.min_arb_edge_percent):
                continue

            for trade in getattr(opp, "recommended_trades", []) or []:
                if not isinstance(trade, dict):
                    continue
                decision_market_id = str(trade.get("market_id", "")).strip()
                if not decision_market_id or decision_market_id not in market_index:
                    continue

                side = str(trade.get("side", "")).strip().upper()
                if side not in {"YES", "NO"}:
                    continue

                market = market_index[decision_market_id]
                trade_price = float(
                    trade.get("price", market.yes_price if side == "YES" else market.no_price)
                )
                if trade_price <= 0:
                    trade_price = float(market.yes_price) if side == "YES" else float(market.no_price)
                try:
                    explicit_size = float(trade.get("size_usd", 0.0) or 0.0)
                except (TypeError, ValueError):
                    explicit_size = 0.0
                if explicit_size > 0:
                    size = explicit_size
                else:
                    size = float(self.config.max_position_usd) * 0.6
                    size = max(size, float(self.config.min_position_usd))
                basket_id = str(trade.get("basket_id", "") or "").strip()
                basket_leg_count = str(trade.get("basket_leg_count", "") or "").strip()
                prediction_path = ""
                if basket_id and basket_leg_count:
                    prediction_path = f"arb_basket|{basket_id}|{basket_leg_count}"
                decisions.append(
                    (
                        TradeDecision(
                            market_id=decision_market_id,
                            timestamp=datetime.utcnow(),
                            should_trade=True,
                            side=side,
                            size_usd=size,
                            price=trade_price,
                            confidence=0.75,
                            reason=(
                                f"Arbitrage {getattr(opp, 'arb_type', 'arb')} "
                                f"edge={float(getattr(opp, 'edge_percent', 0.0)):.2f}%"
                            ),
                            source="arbitrage",
                            prediction_path=prediction_path,
                        ),
                        market,
                        "arbitrage",
                    )
                )

        return decisions

    def _execute_cycle_plan(
        self,
        candidate_decisions: List[Tuple[TradeDecision, CLIMarket, str]],
        cycle_summary: Dict[str, Any],
    ) -> Dict[str, List[Dict[str, Any]]]:
        planned: List[Dict[str, Any]] = []
        executed: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        blocked: List[Dict[str, Any]] = []
        rejections: List[Dict[str, Any]] = []
        fill_outcomes: List[Dict[str, Any]] = []

        risk_summary = self.risk_manager.get_risk_summary()
        if risk_summary.get("halted"):
            for decision, market, source in candidate_decisions:
                blocked.append(
                    self._record_blocked_reason(
                        decision=decision,
                        market=market,
                        source=source,
                        reason="RISK_HALT",
                        detail=str(risk_summary.get("halt_reason") or "risk halted"),
                    )
                )
            return {
                "planned": planned,
                "executed": executed,
                "skipped": skipped,
                "blocked": blocked,
                "rejections": rejections,
                "fill_outcomes": fill_outcomes,
            }

        if self._is_weather_vertical() and self.config.execution_mode == ExecutionMode.LIVE:
            live_report = WeatherLiveEligibilityGate(self.config).evaluate()
            if live_report.eligible:
                live_report = None
            else:
                blockers = list(live_report.blockers or [])
                detail = (
                    f"status={live_report.status}; blockers="
                    f"{', '.join(blockers[:8]) if blockers else 'unknown'}"
                )
                cycle_summary["weather_live_eligibility"] = live_report.to_dict()
                cycle_summary.setdefault("cycle_errors", []).append(
                    {
                        "phase": "weather_live_eligibility",
                        "error": detail,
                    }
                )
        else:
            live_report = None

        if live_report is not None:
            for decision, market, source in candidate_decisions:
                blocked.append(
                    self._record_blocked_reason(
                        decision=decision,
                        market=market,
                        source=source,
                        reason="WEATHER_LIVE_ELIGIBILITY_FAILED",
                        detail=detail,
                    )
                )
            self._total_rejections += len(candidate_decisions)
            return {
                "planned": planned,
                "executed": executed,
                "skipped": skipped,
                "blocked": blocked,
                "rejections": rejections,
                "fill_outcomes": fill_outcomes,
            }

        remaining_budget = float(self.config.max_total_exposure_usd) - self.risk_manager.total_exposure
        if remaining_budget < 0.0:
            remaining_budget = 0.0
        candidate_decisions, basket_blocked = self._precheck_arbitrage_baskets(
            candidate_decisions,
            remaining_budget,
        )
        blocked.extend(basket_blocked)
        self._total_rejections += len(basket_blocked)
        candidate_decisions = self._order_arbitrage_basket_legs(candidate_decisions)
        basket_states: Dict[str, Dict[str, Any]] = {}
        processed_market_ids = set()

        for decision, market, source in candidate_decisions:
            basket_key = self._arbitrage_basket_key(decision)
            if basket_key:
                basket_state = basket_states.setdefault(
                    basket_key,
                    {"failed": False, "failure_reason": "", "executions": []},
                )
                if basket_state.get("failed"):
                    blocked.append(
                        self._record_blocked_reason(
                            decision=decision,
                            market=market,
                            source=source,
                            reason="ARBITRAGE_BASKET_ABORTED",
                            detail=str(basket_state.get("failure_reason") or "prior basket leg failed"),
                        )
                    )
                    self._total_rejections += 1
                    continue

            if not decision.market_id:
                skipped.append(
                    {
                        "phase": "invalid_input",
                        "source": source,
                        "market_id": "",
                        "side": str(decision.side or ""),
                        "requested": round(float(decision.size_usd or 0.0), 2),
                        "reason": {
                            "phase": "validation",
                            "reason": "missing market_id",
                            "execution_mode": self.config.execution_mode.value,
                        },
                    }
                )
                rejections.append({"phase": "validation", "reason": "missing market_id"})
                self._total_rejections += 1
                continue

            if decision.market_id in processed_market_ids:
                blocked.append(
                    self._record_blocked_reason(
                        decision=decision,
                        market=market,
                        source=source,
                        reason="DUPLICATE_MARKET_PLAN",
                        detail="already processed a trade plan for this market in this cycle",
                    )
                )
                self._total_rejections += 1
                continue
            processed_market_ids.add(decision.market_id)

            planned.append(
                {
                    "phase": "planned",
                    "market_id": decision.market_id,
                    "source": source,
                    "side": decision.side,
                    "size_usd": round(float(decision.size_usd or 0.0), 2),
                    "price": round(float(decision.price or 0.0), 4),
                }
            )

            if remaining_budget <= 0:
                blocked.append(
                    self._record_blocked_reason(
                        decision=decision,
                        market=market,
                        source=source,
                        reason="BUDGET_EXHAUSTED",
                        detail=(
                            f"remaining_budget={remaining_budget:.2f}, "
                            f"exposure={self.risk_manager.total_exposure:.2f}"
                        ),
                    )
                )
                self._total_rejections += 1
                continue

            planned_size = float(decision.size_usd or 0.0)
            can_trade, risk_reason = self.risk_manager.can_trade(
                market_id=decision.market_id,
                size_usd=min(planned_size, remaining_budget),
                symbol=self.risk_manager.normalize_symbol(getattr(market, "symbol", "")),
                side=decision.side,
                end_date=getattr(market, "end_date", None),
                source=source,
            )
            if not can_trade:
                blocked.append(
                    self._record_blocked_reason(
                        decision=decision,
                        market=market,
                        source=source,
                        reason="RISK_REJECT",
                        detail=risk_reason,
                    )
                )
                self._total_rejections += 1
                continue

            if planned_size > remaining_budget:
                planned_size = max(0.0, remaining_budget)

            if planned_size < float(self.config.min_position_usd):
                blocked.append(
                    self._record_blocked_reason(
                        decision=decision,
                        market=market,
                        source=source,
                        reason="BUDGET_BELOW_MIN_SIZE",
                        detail=(
                            f"requested={float(decision.size_usd or 0.0):.2f} "
                            f"remaining_budget={remaining_budget:.2f}"
                        ),
                    )
                    )
                self._total_rejections += 1
                continue

            execution_decision = decision
            if planned_size != float(decision.size_usd or 0.0):
                execution_decision = TradeDecision(
                    market_id=decision.market_id,
                    timestamp=decision.timestamp,
                    should_trade=True,
                    side=decision.side,
                    size_usd=planned_size,
                    price=decision.price,
                    confidence=decision.confidence,
                    reason=f"{decision.reason} [budget-adjusted]",
                    source=decision.source,
                    prediction_path=str(getattr(decision, "prediction_path", "") or ""),
                )

            try:
                execution = self.trader.execute_trade(execution_decision, market)
            except Exception as exc:
                exc_reason = {
                    "phase": "execution_exception",
                    "reason": str(exc),
                    "error_type": exc.__class__.__name__,
                    "execution_mode": self.config.execution_mode.value,
                }
                skipped.append(
                    {
                        "phase": "execution_exception",
                        "source": source,
                        "market_id": decision.market_id,
                        "side": decision.side,
                        "requested": round(float(decision.size_usd or 0.0), 2),
                        "executed_size": round(planned_size, 2),
                        "reason": exc_reason,
                    }
                )
                rejections.append(exc_reason)
                if basket_key:
                    fill_outcomes.extend(
                        self._mark_arbitrage_basket_failed(
                            basket_key,
                            basket_states,
                            f"execution_exception:{exc.__class__.__name__}",
                        )
                    )
                self._total_rejections += 1
                continue

            if execution is None:
                reject_reason = self.trader.last_reject_reason or {
                    "phase": "execution",
                    "reason": "unknown",
                    "execution_mode": self.config.execution_mode.value,
                    "market_id": decision.market_id,
                }
                skipped.append(
                    {
                        "phase": "execution_failed",
                        "source": source,
                        "market_id": decision.market_id,
                        "side": decision.side,
                        "requested": round(float(decision.size_usd or 0.0), 2),
                        "executed_size": round(planned_size, 2),
                        "reason": reject_reason,
                    }
                )
                rejections.append(reject_reason)
                if basket_key:
                    fill_outcomes.extend(
                        self._mark_arbitrage_basket_failed(
                            basket_key,
                            basket_states,
                            str(reject_reason.get("reason", "execution_failed"))
                            if isinstance(reject_reason, dict)
                            else str(reject_reason),
                        )
                    )
                self._total_rejections += 1
                continue

            if getattr(execution, "status", "") in {"simulated", "paper_filled"}:
                # In paper/dry-run these are deterministic and recorded.
                self._total_trades += 1
                remaining_budget = max(0.0, remaining_budget - float(execution.size_usd or 0.0))
                if basket_key:
                    basket_states.setdefault(
                        basket_key,
                        {"failed": False, "failure_reason": "", "executions": []},
                    )["executions"].append(execution)
                executed.append(
                    {
                        "phase": "executed",
                        "source": source,
                        "market_id": execution.market_id,
                        "side": execution.side,
                        "size_usd": round(float(execution.size_usd or 0.0), 2),
                        "price": round(float(execution.price or 0.0), 4),
                        "status": execution.status,
                        "execution_mode": execution.execution_mode,
                        "order_id": execution.order_id,
                    }
                )
                if self.trader.last_fill_status:
                    fill_outcomes.append(self.trader.last_fill_status)
                continue

            # For live mode, require explicit fill success.
            if execution.status == "filled":
                self._total_trades += 1
                remaining_budget = max(0.0, remaining_budget - float(execution.size_usd or 0.0))
                if basket_key:
                    basket_states.setdefault(
                        basket_key,
                        {"failed": False, "failure_reason": "", "executions": []},
                    )["executions"].append(execution)
                executed.append(
                    {
                        "phase": "executed",
                        "source": source,
                        "market_id": execution.market_id,
                        "side": execution.side,
                        "size_usd": round(float(execution.size_usd or 0.0), 2),
                        "price": round(float(execution.price or 0.0), 4),
                        "status": execution.status,
                        "execution_mode": execution.execution_mode,
                        "order_id": execution.order_id,
                    }
                )
                if self.trader.last_fill_status:
                    fill_outcomes.append(self.trader.last_fill_status)
            else:
                skipped.append(
                    {
                        "phase": "execution_failed",
                        "source": source,
                        "market_id": decision.market_id,
                        "side": decision.side,
                        "requested": round(float(decision.size_usd or 0.0), 2),
                        "executed_size": round(planned_size, 2),
                        "reason": self.trader.last_reject_reason,
                    }
                )
                if self.trader.last_reject_reason:
                    rejections.append(self.trader.last_reject_reason)
                if basket_key:
                    reason = self.trader.last_reject_reason or {"reason": "execution_failed"}
                    fill_outcomes.extend(
                        self._mark_arbitrage_basket_failed(
                            basket_key,
                            basket_states,
                            str(reason.get("reason", "execution_failed"))
                            if isinstance(reason, dict)
                            else str(reason),
                        )
                    )
                self._total_rejections += 1

        return {
            "planned": planned,
            "executed": executed,
            "skipped": skipped,
            "blocked": blocked,
            "rejections": rejections,
            "fill_outcomes": fill_outcomes,
        }

    @staticmethod
    def _arbitrage_basket_key(decision: TradeDecision) -> str:
        basket_key = str(getattr(decision, "prediction_path", "") or "")
        return basket_key if basket_key.startswith("arb_basket|") else ""

    def _order_arbitrage_basket_legs(
        self,
        candidate_decisions: List[Tuple[TradeDecision, CLIMarket, str]],
    ) -> List[Tuple[TradeDecision, CLIMarket, str]]:
        basket_groups: Dict[str, List[Tuple[TradeDecision, CLIMarket, str]]] = {}
        ordered: List[Tuple[TradeDecision, CLIMarket, str]] = []
        seen_baskets: List[str] = []
        for item in candidate_decisions:
            basket_key = self._arbitrage_basket_key(item[0])
            if not basket_key:
                ordered.append(item)
                continue
            if basket_key not in basket_groups:
                seen_baskets.append(basket_key)
            basket_groups.setdefault(basket_key, []).append(item)

        for basket_key in seen_baskets:
            # Execute expensive legs first. If liquidity disappears, fail before
            # cheaper legs have accumulated as a partial basket.
            ordered.extend(
                sorted(
                    basket_groups.get(basket_key, []),
                    key=lambda item: float(item[0].price or 0.0),
                    reverse=True,
                )
            )
        return ordered

    def _mark_arbitrage_basket_failed(
        self,
        basket_key: str,
        basket_states: Dict[str, Dict[str, Any]],
        reason: str,
    ) -> List[Dict[str, Any]]:
        state = basket_states.setdefault(
            basket_key,
            {"failed": False, "failure_reason": "", "executions": []},
        )
        if state.get("failed"):
            return []
        state["failed"] = True
        state["failure_reason"] = reason or "basket leg failed"
        prior_executions = list(state.get("executions", []) or [])
        if self.config.execution_mode != ExecutionMode.LIVE or not prior_executions:
            return []
        return self._unwind_live_arbitrage_basket(
            basket_key=basket_key,
            executions=prior_executions,
            reason=state["failure_reason"],
        )

    def _unwind_live_arbitrage_basket(
        self,
        basket_key: str,
        executions: List[Any],
        reason: str,
    ) -> List[Dict[str, Any]]:
        unwind_results: List[Dict[str, Any]] = []
        failed_unwinds = 0
        for execution in reversed(executions):
            market_id = str(getattr(execution, "market_id", "") or "")
            close_price = float(getattr(execution, "price", 0.0) or 0.0)
            pnl = None
            if market_id and close_price > 0:
                try:
                    pnl = self.trader.close_position(
                        market_id,
                        close_price,
                        reason="arbitrage_basket_abort",
                    )
                except Exception as exc:
                    pnl = None
                    unwind_results.append(
                        {
                            "status": "arbitrage_basket_unwind_exception",
                            "basket_key": basket_key,
                            "market_id": market_id,
                            "reason": str(exc),
                            "error_type": exc.__class__.__name__,
                        }
                    )
            ok = pnl is not None
            if not ok:
                failed_unwinds += 1
            unwind_results.append(
                {
                    "status": "arbitrage_basket_unwind",
                    "basket_key": basket_key,
                    "market_id": market_id,
                    "closed": ok,
                    "realized_pnl": pnl,
                    "abort_reason": reason,
                }
            )

        halt_reason = (
            f"Arbitrage basket {basket_key} aborted after partial live fills; "
            f"unwind_failures={failed_unwinds}"
        )
        self.risk_manager.halt_trading(halt_reason, "ARB_BASKET_PARTIAL")
        return unwind_results

    def _precheck_arbitrage_baskets(
        self,
        candidate_decisions: List[Tuple[TradeDecision, CLIMarket, str]],
        remaining_budget: float,
    ) -> Tuple[List[Tuple[TradeDecision, CLIMarket, str]], List[Dict[str, Any]]]:
        basket_groups: Dict[str, List[Tuple[TradeDecision, CLIMarket, str]]] = {}
        for item in candidate_decisions:
            decision = item[0]
            basket_key = str(getattr(decision, "prediction_path", "") or "")
            if basket_key.startswith("arb_basket|"):
                basket_groups.setdefault(basket_key, []).append(item)
        if not basket_groups:
            return candidate_decisions, []

        blocked_keys = set()
        blocked: List[Dict[str, Any]] = []
        open_slots = max(0, int(self.config.max_positions) - len(self.risk_manager.positions))
        current_symbol_counts: Dict[str, int] = {}
        current_direction_counts: Dict[Tuple[str, str], int] = {}
        for position in self.risk_manager.positions.values():
            symbol = self.risk_manager.normalize_symbol(getattr(position, "symbol", ""))
            side = str(getattr(position, "side", "") or "").upper()
            current_symbol_counts[symbol] = current_symbol_counts.get(symbol, 0) + 1
            current_direction_counts[(symbol, side)] = current_direction_counts.get((symbol, side), 0) + 1

        for basket_key, items in basket_groups.items():
            parts = basket_key.split("|")
            try:
                expected_legs = int(parts[-1])
            except (TypeError, ValueError):
                expected_legs = 0
            total_size = sum(float(item[0].size_usd or 0.0) for item in items)
            reason = ""
            if expected_legs <= 0 or len(items) != expected_legs:
                reason = f"incomplete basket legs {len(items)}/{expected_legs}"
            elif len(items) > open_slots:
                reason = f"position slots {open_slots} < basket legs {len(items)}"
            elif total_size > remaining_budget:
                reason = f"remaining budget {remaining_budget:.2f} < basket cost {total_size:.2f}"
            else:
                for _decision, market, _source in items:
                    symbol = self.risk_manager.normalize_symbol(getattr(market, "symbol", ""))
                    side = str(_decision.side or "").upper()
                    if current_symbol_counts.get(symbol, 0) + len(items) > int(self.config.max_positions_per_symbol):
                        reason = f"symbol slots insufficient for {symbol} basket"
                        break
                    if (
                        current_direction_counts.get((symbol, side), 0) + len(items)
                        > int(getattr(self.config, "max_positions_per_direction", 3))
                    ):
                        reason = f"direction slots insufficient for {symbol} {side} basket"
                        break
            if not reason:
                continue
            blocked_keys.add(basket_key)
            for decision, market, source in items:
                blocked.append(
                    self._record_blocked_reason(
                        decision=decision,
                        market=market,
                        source=source,
                        reason="ARBITRAGE_BASKET_PRECHECK",
                        detail=reason,
                    )
                )

        if not blocked_keys:
            return candidate_decisions, []
        filtered = [
            item
            for item in candidate_decisions
            if str(getattr(item[0], "prediction_path", "") or "") not in blocked_keys
        ]
        return filtered, blocked

    def _record_blocked_reason(
        self,
        decision: TradeDecision,
        market: CLIMarket,
        source: str,
        reason: str,
        detail: str,
    ) -> Dict[str, Any]:
        return {
            "phase": "blocked",
            "source": source,
            "market_id": decision.market_id,
            "question": market.question,
            "side": decision.side,
            "size_usd": round(float(decision.size_usd or 0.0), 2),
            "reason": reason,
            "detail": detail,
        }

    def _record_cycle_summary(self, summary: Dict[str, Any]):
        self.config.ensure_dirs()
        cycles_dir = self.config.cycles_dir
        cycles_dir.mkdir(parents=True, exist_ok=True)
        timestamp = summary.get("started_at", datetime.utcnow().isoformat())
        fname = f"cycle_{int(summary.get('cycle', 0)):04d}_{self._compact_timestamp(timestamp)}.json"
        path = cycles_dir / fname
        try:
            with open(path, "w") as f:
                json.dump(summary, f, indent=2, default=str)
        except Exception as exc:
            cprint(f"Failed writing cycle summary: {exc}", "red")

    def _write_cycle_progress(self, summary: Dict[str, Any]):
        self.config.ensure_dirs()
        progress_path = self.config.data_dir / "current_cycle.json"
        try:
            with open(progress_path, "w") as f:
                json.dump(summary, f, indent=2, default=str)
        except Exception as exc:
            cprint(f"Failed writing current cycle progress: {exc}", "yellow")

    def _update_cycle_progress(
        self,
        summary: Dict[str, Any],
        phase: str,
        status: str,
        *,
        phase_started: Optional[float] = None,
        error: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        event: Dict[str, Any] = {
            "phase": phase,
            "status": status,
            "timestamp": datetime.utcnow().isoformat(),
        }
        if phase_started is not None:
            event["elapsed_seconds"] = round(max(0.0, time.perf_counter() - phase_started), 3)
        if error:
            event["error"] = error
        if details:
            event["details"] = details
        summary.setdefault("phase_progress", []).append(event)
        summary["current_phase"] = phase
        summary["current_phase_status"] = status
        summary["progress_updated_at"] = event["timestamp"]
        self._write_cycle_progress(summary)

    def _append_run_log_line(self, summary: Dict[str, Any]):
        """
        Append a compact line-per-cycle audit payload for dashboards.
        """
        self.config.ensure_dirs()
        run_log = self.config.data_dir / "run_audit.jsonl"
        payload = {
            "timestamp": summary.get("started_at"),
            "cycle": summary.get("cycle"),
            "execution_mode": summary.get("execution_mode"),
            "status": summary.get("status"),
            "budget_before_usd": summary.get("budget_before_usd"),
            "budget_after_usd": summary.get("budget_after_usd"),
            "markets_found": summary.get("markets_found", 0),
            "trades_planned": len(summary.get("planned", [])),
            "trades_executed": len(summary.get("executed", [])),
            "trades_blocked": len(summary.get("blocked", [])),
            "trades_skipped": len(summary.get("skipped", [])),
            "cycle_errors": summary.get("cycle_errors", []),
            "rejections": summary.get("rejections", []),
            "fill_outcomes": summary.get("fill_outcomes", []),
            "live_order_events": summary.get("live_order_events", []),
            "swarm_runtime": summary.get("swarm_runtime", {}),
            "scanner_telemetry": summary.get("scanner_telemetry", {}),
            "phase_progress": summary.get("phase_progress", []),
            "resolution_source_errors": summary.get("resolution_source_errors", summary.get("resolved_markets", [])),
            "weather_evidence": summary.get("weather_evidence", {}),
            "fallback_reasons": [
                {"source": r.get("source"), "reason": r.get("reason")}
                for r in (
                    list(summary.get("rejections", []))
                    + list(summary.get("blocked", []))
                    + list(summary.get("skipped", []))
                )
                if isinstance(r, dict)
            ],
            "risk_status": summary.get("risk_status_after")
            or summary.get("risk_status_before", {}),
            "paper_balance": summary.get("paper_balance", self.trader.get_paper_balance()),
        }
        try:
            with open(run_log, "a") as f:
                f.write(json.dumps(payload) + "\n")
        except Exception as exc:
            cprint(f"Failed writing run audit line: {exc}", "yellow")

    def _write_cycle_summary(self, summary: Dict[str, Any]):
        if not summary:
            return
        self._record_cycle_summary(summary)

    @staticmethod
    def _compact_timestamp(timestamp: str) -> str:
        return timestamp.replace(":", "").replace("-", "").replace("T", "_").replace("Z", "")

    def _print_cycle_summary(self, summary: Dict[str, Any]):
        trades_executed = len(summary.get("executed", []))
        trades_blocked = len(summary.get("blocked", []))
        trades_skipped = len(summary.get("skipped", []))
        risk = summary.get("risk_status_after") or {}
        status = summary.get("status", "unknown")
        cprint(
            f"[Cycle {summary.get('cycle')}] status={status} executed={trades_executed} "
            f"blocked={trades_blocked} skipped={trades_skipped} "
            f"positions={risk.get('positions', 0)}/{risk.get('max_positions', 0)} "
            f"exposure={risk.get('total_exposure', 0):.2f}/{risk.get('max_exposure', 0):.2f}",
            "cyan",
        )

        if summary.get("rejections"):
            for item in summary.get("rejections")[:3]:
                cprint(f"  Reject: {item}", "yellow")

        if summary.get("fill_outcomes"):
            for item in summary.get("fill_outcomes")[:3]:
                cprint(f"  Fill: {item}", "yellow")

        if summary.get("resolution_source_errors"):
            for item in summary.get("resolution_source_errors")[:3]:
                cprint(f"  Resolution: {item}", "yellow")
