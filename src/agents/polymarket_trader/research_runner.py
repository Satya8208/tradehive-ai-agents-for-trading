"""
Research Runner — Continuous Paper Trading + Scoring + Optimization Loop

Connects paper trading (orchestrator) with backtest scoring and parameter
optimization in a closed feedback loop:

  1. Paper trade N cycles on live markets (no real money)
  2. Score accumulated results (historical + new)
  3. Optimize parameters (fast mutation search)
  4. Print dashboard, optionally apply improved params
  5. Repeat forever

Usage:
    python -m src.agents.polymarket_trader.research_runner
    python -m src.agents.polymarket_trader.research_runner --max-expiry-hours 4 --auto-apply
    python -m src.agents.polymarket_trader.research_runner --trading-cycles 3 --optimize-rounds 20
"""

import argparse
import csv
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from termcolor import cprint

from .backtest_scorer import BacktestScorer, ParamSet, BacktestResult
from .auto_optimize import AutoOptimizer, SEARCH_SPACE, DISCRETE_SPACE
from .config import PolymarketCLIConfig, ExecutionMode
from .orchestrator import PolymarketCLIOrchestrator


# =========================================================================
# DATA CLASSES
# =========================================================================

@dataclass
class ResearchSession:
    """Tracks research session state across iterations."""
    session_id: str
    start_time: datetime
    data_dir: Path
    total_trading_cycles: int = 0
    total_trades: int = 0
    total_resolved: int = 0
    scoring_rounds: int = 0
    score_history: list = field(default_factory=list)
    best_params: Optional[ParamSet] = None
    best_score: float = 0.0
    paper_balance: float = 500.0


# =========================================================================
# OPTIMIZER WITH INJECTED SCORER
# =========================================================================

class ResearchOptimizer(AutoOptimizer):
    """AutoOptimizer that uses a custom BacktestScorer with specified data dirs."""

    def __init__(self, data_dirs: List[str],
                 results_path: str = "src/data/polymarket_trader/research_optimization.tsv"):
        # Don't call super().__init__ — we inject our own scorer
        self._data_dirs = data_dirs
        self.scorer = BacktestScorer(data_dirs=data_dirs)
        self.results_path = Path(results_path)
        self.results_path.parent.mkdir(parents=True, exist_ok=True)

        self.best_params = ParamSet()
        self.best_result = self.scorer.score(self.best_params)
        self.best_score = self.best_result.score

        self.round_num = 0
        self.improvements = 0
        self.discards = 0

        self._init_results_file()

    def reload(self):
        """Re-read trade files from disk (call after new trades resolve)."""
        self.scorer = BacktestScorer(data_dirs=self._data_dirs)


# =========================================================================
# RESEARCH RUNNER
# =========================================================================

class ResearchRunner:
    """
    Continuous feedback loop: paper trade -> score -> optimize -> apply -> repeat.

    Runs the orchestrator in PAPER mode, periodically scores accumulated trades,
    and optionally applies optimized parameters to the next trading session.
    """

    # Standard historical data directories (same as BacktestScorer defaults)
    HISTORICAL_DIRS = [
        "src/data/polymarket_cli",
        "src/data/polymarket_cli_weekly",
        "src/data/polymarket_cli_intraday",
        "src/data/polymarket_cli_daily",
        "src/data/polymarket_trader_daily",
        "src/data/polymarket_trader_weekly",
        "src/data/polymarket_trader_short",
        "src/data/polymarket_trader",
    ]

    def __init__(self, balance=500.0, trading_cycles=5, scoring_interval=1,
                 optimize_rounds=30, max_expiry_hours=24.0, min_expiry_hours=None,
                 auto_apply=False, markets_per_cycle=5, cycle_interval=60,
                 data_dir=None):
        self.balance = balance
        self.trading_cycles = trading_cycles
        self.scoring_interval = scoring_interval
        self.optimize_rounds = optimize_rounds
        self.max_expiry_hours = max_expiry_hours
        self.min_expiry_hours = min_expiry_hours
        self.auto_apply = auto_apply
        self.markets_per_cycle = markets_per_cycle
        self.cycle_interval = cycle_interval

        # Session setup
        session_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        if data_dir:
            research_dir = Path(data_dir)
        else:
            research_dir = Path(f"src/data/polymarket_research_{session_id}")

        self.session = ResearchSession(
            session_id=session_id,
            start_time=datetime.utcnow(),
            data_dir=research_dir,
            paper_balance=balance,
        )

        self._applied_params: Optional[ParamSet] = None
        self._running = False

    def run(self):
        """Main research loop. Ctrl+C for graceful shutdown."""
        self._print_banner()
        self._running = True
        session_num = 0

        try:
            while self._running:
                session_num += 1
                cprint(f"\n{'='*70}", "cyan")
                cprint(f"  RESEARCH SESSION #{session_num}", "cyan", attrs=["bold"])
                cprint(f"{'='*70}", "cyan")

                # Phase 1: Paper Trading
                self._run_trading_phase()

                # Phase 2: Score
                if session_num % self.scoring_interval == 0:
                    result = self._run_scoring_phase()

                    # Phase 3: Optimize (if enough resolved trades)
                    if result and result.filtered_trades >= 5:
                        self._run_optimization_phase()

                    # Phase 4: Dashboard
                    self._print_dashboard()

                    # Phase 5: Apply optimized params
                    if self.auto_apply and self.session.best_params:
                        self._apply_params(self.session.best_params)

                # Log session state
                self._log_session()

        except KeyboardInterrupt:
            cprint("\n\nResearch interrupted — printing final summary...", "yellow")
        finally:
            self._print_final_summary()

    # =====================================================================
    # PHASES
    # =====================================================================

    def _run_trading_phase(self):
        """Run N paper trading cycles via the orchestrator."""
        cprint(f"\n[TRADE] Running {self.trading_cycles} paper cycles...", "cyan")

        config = self._build_config()
        orchestrator = PolymarketCLIOrchestrator(config)
        orchestrator.run(cycles=self.trading_cycles)

        # Update session counters
        self.session.total_trading_cycles += self.trading_cycles
        self.session.total_trades += orchestrator._total_trades

        # Persist paper balance for next session
        self.session.paper_balance = orchestrator.trader._paper_balance
        cprint(f"[TRADE] Paper balance: ${self.session.paper_balance:.2f}", "white")

    def _run_scoring_phase(self) -> Optional[BacktestResult]:
        """Score accumulated trades from all data directories."""
        cprint(f"\n[SCORE] Scoring accumulated trades...", "cyan")

        data_dirs = self._get_all_data_dirs()
        scorer = BacktestScorer(data_dirs=data_dirs)

        if not scorer.trades:
            cprint("[SCORE] No resolved trades yet — waiting for markets to close", "yellow")
            return None

        params = self.session.best_params or ParamSet()
        result = scorer.score(params)

        self.session.total_resolved = result.total_trades
        self.session.scoring_rounds += 1
        self.session.score_history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "score": result.score,
            "win_rate": result.win_rate,
            "pnl": result.total_pnl,
            "roi": result.roi,
            "trades": result.filtered_trades,
            "total_trades": result.total_trades,
        })

        color = "green" if result.total_pnl >= 0 else "red"
        cprint(f"[SCORE] score={result.score:.1f} | "
               f"WR={result.win_rate:.0%} | "
               f"P&L=${result.total_pnl:+.2f} | "
               f"trades={result.filtered_trades}/{result.total_trades}",
               color)

        return result

    def _run_optimization_phase(self):
        """Run parameter optimization on accumulated data."""
        cprint(f"\n[OPTIMIZE] Running {self.optimize_rounds} mutation rounds...", "cyan")

        data_dirs = self._get_all_data_dirs()
        opt_path = str(self.session.data_dir / "research_optimization.tsv")

        optimizer = ResearchOptimizer(data_dirs=data_dirs, results_path=opt_path)

        # Seed with current best if we have one
        if self.session.best_params:
            optimizer.best_params = self.session.best_params
            optimizer.best_result = optimizer.scorer.score(self.session.best_params)
            optimizer.best_score = optimizer.best_result.score

        optimizer.run(max_rounds=self.optimize_rounds)

        # Update session
        if optimizer.best_score > self.session.best_score:
            self.session.best_params = optimizer.best_params
            self.session.best_score = optimizer.best_score
            cprint(f"[OPTIMIZE] New best: score={optimizer.best_score:.1f}", "green")
        else:
            cprint(f"[OPTIMIZE] No improvement (best={self.session.best_score:.1f})", "white")

    def _apply_params(self, params: ParamSet):
        """Store optimized params to apply in next trading session."""
        self._applied_params = params
        cprint(f"[APPLY] Next session will use optimized params:", "green")
        cprint(f"  edge>={params.min_edge_threshold:.1f}% | "
               f"arb>={params.min_arb_edge_percent:.1f}% | "
               f"kelly={params.kelly_fraction:.2f} | "
               f"max_pos=${params.max_position_usd:.0f}", "green")

    # =====================================================================
    # CONFIG & DATA
    # =====================================================================

    def _build_config(self) -> PolymarketCLIConfig:
        """Build paper trading config, applying optimized params if available."""
        config = PolymarketCLIConfig(
            execution_mode=ExecutionMode.PAPER,
            cycle_interval_seconds=self.cycle_interval,
            max_markets_to_analyze=self.markets_per_cycle,
            paper_starting_balance=self.session.paper_balance,
            max_expiry_hours=self.max_expiry_hours,
            min_expiry_hours=self.min_expiry_hours,
            arb_fuzzy_match_threshold=0.85,
            whale_scan_interval_cycles=3,
        )
        config._data_dir_override = self.session.data_dir

        # Apply optimized params if available
        if self._applied_params:
            p = self._applied_params
            config.min_edge_threshold = p.min_edge_threshold
            config.min_edge_confidence = p.min_edge_confidence
            config.kelly_fraction = p.kelly_fraction
            config.min_arb_edge_percent = p.min_arb_edge_percent
            config.max_position_usd = p.max_position_usd
            config.min_arb_token_price = p.min_arb_token_price

        # Auto-tune for short-expiry markets
        if config.max_expiry_hours is not None:
            if config.max_expiry_hours <= 0.25:
                config.cycle_interval_seconds = 30
                config.swarm_timeout_seconds = 25
                config.market_cache_seconds = 60
            elif config.max_expiry_hours <= 1.0:
                config.cycle_interval_seconds = 45
                config.swarm_timeout_seconds = 35
                config.market_cache_seconds = 120

            cycle_budget = config.cycle_interval_seconds + config.swarm_timeout_seconds + 30
            config.min_expiry_minutes = (cycle_budget / 60.0) * 2.0

        return config

    def _get_all_data_dirs(self) -> List[str]:
        """Return all data directories for scoring (research + historical)."""
        seen = set()
        dirs = []
        for d in [str(self.session.data_dir)] + self.HISTORICAL_DIRS:
            resolved = str(Path(d).resolve())
            if resolved not in seen and Path(d).exists():
                seen.add(resolved)
                dirs.append(d)
        return dirs

    # =====================================================================
    # DISPLAY
    # =====================================================================

    def _print_banner(self):
        cprint("""
    ╔══════════════════════════════════════════════════════════╗
    ║       POLYMARKET RESEARCH RUNNER                        ║
    ║       Paper Trade + Score + Optimize Loop               ║
    ║       Ctrl+C to stop                                    ║
    ╚══════════════════════════════════════════════════════════╝
        """, "cyan")
        cprint(f"  Balance: ${self.balance:,.2f}", "white")
        cprint(f"  Trading Cycles/Session: {self.trading_cycles}", "white")
        cprint(f"  Optimize Rounds/Session: {self.optimize_rounds}", "white")
        cprint(f"  Cycle Interval: {self.cycle_interval}s", "white")
        cprint(f"  Auto-Apply: {self.auto_apply}", "white")
        if self.max_expiry_hours:
            cprint(f"  Max Expiry: {self.max_expiry_hours}h", "white")
        cprint(f"  Data Dir: {self.session.data_dir}", "white")
        cprint(f"  Started: {self.session.start_time.strftime('%Y-%m-%d %H:%M:%S')} UTC\n", "white")

    def _print_dashboard(self):
        cprint(f"\n{'='*70}", "cyan")
        cprint(f"  RESEARCH DASHBOARD — {self.session.session_id}", "cyan", attrs=["bold"])
        cprint(f"{'='*70}", "cyan")

        elapsed = (datetime.utcnow() - self.session.start_time).total_seconds() / 60
        cprint(f"  Runtime: {elapsed:.0f}min | "
               f"Cycles: {self.session.total_trading_cycles} | "
               f"Scores: {self.session.scoring_rounds}", "white")
        cprint(f"  Trades: {self.session.total_trades} entered, "
               f"{self.session.total_resolved} resolved | "
               f"Balance: ${self.session.paper_balance:.2f}", "white")

        if self.session.score_history:
            latest = self.session.score_history[-1]
            color = "green" if latest["pnl"] >= 0 else "red"
            cprint(f"\n  Score: {latest['score']:.1f} | "
                   f"WR: {latest['win_rate']:.0%} | "
                   f"P&L: ${latest['pnl']:+.2f} | "
                   f"ROI: {latest['roi']:.1%} | "
                   f"Trades: {latest['trades']}", color)

            # Trend (last 5)
            if len(self.session.score_history) >= 2:
                cprint(f"\n  Score Trend:", "cyan")
                for i, h in enumerate(self.session.score_history[-5:]):
                    delta = ""
                    if i > 0:
                        prev_list = self.session.score_history[-5:]
                        d = h["score"] - prev_list[i-1]["score"]
                        delta = f" ({d:+.1f})"
                    cprint(f"    {h['timestamp'][:19]}: "
                           f"score={h['score']:.1f}{delta} | "
                           f"{h['trades']}t {h['win_rate']:.0%}WR", "white")

        if self.session.best_params:
            p = self.session.best_params
            cprint(f"\n  Best Params (score={self.session.best_score:.1f}):", "green")
            cprint(f"    edge>={p.min_edge_threshold:.1f}% | "
                   f"arb>={p.min_arb_edge_percent:.1f}% | "
                   f"kelly={p.kelly_fraction:.2f} | "
                   f"max_pos=${p.max_position_usd:.0f}", "white")
            cprint(f"    symbols={p.allowed_symbols} | "
                   f"swarm={p.allow_swarm} | arb={p.allow_arb}", "white")

        cprint(f"{'='*70}\n", "cyan")

    def _print_final_summary(self):
        cprint(f"\n{'='*70}", "cyan")
        cprint(f"  RESEARCH COMPLETE", "cyan", attrs=["bold"])
        cprint(f"{'='*70}", "cyan")

        elapsed = (datetime.utcnow() - self.session.start_time).total_seconds() / 60
        cprint(f"  Total Runtime: {elapsed:.0f} minutes", "white")
        cprint(f"  Trading Cycles: {self.session.total_trading_cycles}", "white")
        cprint(f"  Trades Entered: {self.session.total_trades}", "white")
        cprint(f"  Trades Resolved: {self.session.total_resolved}", "white")
        cprint(f"  Scoring Rounds: {self.session.scoring_rounds}", "white")
        cprint(f"  Final Balance: ${self.session.paper_balance:.2f}", "white")

        if self.session.score_history:
            latest = self.session.score_history[-1]
            cprint(f"\n  Final Score: {latest['score']:.1f} | "
                   f"WR: {latest['win_rate']:.0%} | "
                   f"P&L: ${latest['pnl']:+.2f}", "green")

        if self.session.best_params:
            p = self.session.best_params
            cprint(f"\n  Best Params Found:", "green")
            cprint(f"    min_edge_threshold:  {p.min_edge_threshold:.1f}%", "white")
            cprint(f"    min_arb_edge:        {p.min_arb_edge_percent:.1f}%", "white")
            cprint(f"    kelly_fraction:      {p.kelly_fraction:.2f}", "white")
            cprint(f"    max_position_usd:    ${p.max_position_usd:.0f}", "white")
            cprint(f"    allowed_symbols:     {p.allowed_symbols}", "white")

        cprint(f"\n  Data: {self.session.data_dir}", "white")
        cprint(f"{'='*70}", "cyan")

    # =====================================================================
    # LOGGING
    # =====================================================================

    def _log_session(self):
        """Append session state to research log."""
        self.session.data_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.session.data_dir / "research_log.tsv"

        write_header = not log_path.exists()
        with open(log_path, "a", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            if write_header:
                writer.writerow([
                    "timestamp", "trading_cycles", "trades_entered",
                    "trades_resolved", "scoring_rounds", "score",
                    "win_rate", "pnl", "roi", "balance"
                ])

            latest = self.session.score_history[-1] if self.session.score_history else {}
            writer.writerow([
                datetime.utcnow().isoformat(),
                self.session.total_trading_cycles,
                self.session.total_trades,
                self.session.total_resolved,
                self.session.scoring_rounds,
                f"{latest.get('score', 0):.2f}",
                f"{latest.get('win_rate', 0):.3f}",
                f"{latest.get('pnl', 0):.2f}",
                f"{latest.get('roi', 0):.4f}",
                f"{self.session.paper_balance:.2f}",
            ])


# =========================================================================
# CLI ENTRY POINT
# =========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Research Runner — Paper Trade + Score + Optimize loop"
    )
    parser.add_argument("--balance", type=float, default=500.0,
                        help="Paper starting balance (default: $500)")
    parser.add_argument("--trading-cycles", type=int, default=5,
                        help="Trading cycles per session before scoring (default: 5)")
    parser.add_argument("--scoring-interval", type=int, default=1,
                        help="Score every N sessions (default: 1)")
    parser.add_argument("--optimize-rounds", type=int, default=30,
                        help="Optimizer mutations per scoring phase (default: 30)")
    parser.add_argument("--max-expiry-hours", type=float, default=24.0,
                        help="Only trade markets expiring within N hours (default: 24)")
    parser.add_argument("--min-expiry-hours", type=float, default=None,
                        help="Only trade markets expiring after N hours")
    parser.add_argument("--auto-apply", action="store_true",
                        help="Auto-apply optimized params to next trading session")
    parser.add_argument("--markets", type=int, default=5,
                        help="Markets to analyze per cycle (default: 5)")
    parser.add_argument("--interval", type=int, default=60,
                        help="Seconds between trading cycles (default: 60)")
    parser.add_argument("--data-dir", type=str, default=None,
                        help="Override data directory (default: auto-generated)")
    args = parser.parse_args()

    runner = ResearchRunner(
        balance=args.balance,
        trading_cycles=args.trading_cycles,
        scoring_interval=args.scoring_interval,
        optimize_rounds=args.optimize_rounds,
        max_expiry_hours=args.max_expiry_hours,
        min_expiry_hours=args.min_expiry_hours,
        auto_apply=args.auto_apply,
        markets_per_cycle=args.markets,
        cycle_interval=args.interval,
        data_dir=args.data_dir,
    )
    runner.run()


if __name__ == "__main__":
    main()
