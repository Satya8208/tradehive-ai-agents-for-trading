"""
Crypto Polymarket Orchestrator

Main coordination engine that ties all components together.
Runs continuous cycles of data collection, analysis, and trading.

Uses UnifiedDataPipeline for real-time WebSocket data from
Binance, Bybit, and Hyperliquid.

Built with love by TradeHive
"""

import os
import sys
import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from termcolor import cprint

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.config import (
    CryptoPolymarketConfig,
    SignalDirection,
    ExecutionMode,
)
from src.agents.crypto_polymarket.models import (
    MarketSignal,
    AggregatedSignal,
    CryptoMarket,
    SwarmAnalysisResult,
    TradeDecision,
    TradeExecution,
    OrchestratorCycleResult,
)

# Data Pipeline
from src.data.connectors.unified_pipeline import UnifiedDataPipeline

# Data Agents (v2.1: 5 agents + whale)
from src.agents.crypto_polymarket.data_agents.whale_agent import WhaleAgent
from src.agents.crypto_polymarket.data_agents.liquidation_agent import LiquidationAgent
from src.agents.crypto_polymarket.data_agents.funding_agent import FundingAgent
from src.agents.crypto_polymarket.data_agents.open_interest_agent import (
    OpenInterestAgent,
)
from src.agents.crypto_polymarket.data_agents.volume_agent import VolumeAgent
from src.agents.crypto_polymarket.data_agents.orderbook_agent import (
    OrderBookImbalanceAgent,
)

# Intelligence Components (v2.0: Timeframe + Regime + Edge)
from src.agents.crypto_polymarket.timeframe_controller import TimeframeController
from src.agents.crypto_polymarket.regime_detection import RegimeDetectionEngine
from src.agents.crypto_polymarket.edge_calculator import EdgeCalculator
# from src.agents.crypto_polymarket.risk_manager import RiskManager  # Phase 4

# Analysis (v2.0: SignalAggregator with regime support)
from src.agents.crypto_polymarket.analysis.signal_aggregator_v2 import (
    SignalAggregatorV2,
)
from src.agents.crypto_polymarket.analysis.swarm_analyzer import SwarmAnalyzer
from src.agents.crypto_polymarket.analysis.decision_engine import DecisionEngine

# Market Integration
from src.agents.crypto_polymarket.market.scanner import CryptoMarketScanner
from src.agents.crypto_polymarket.market.trader import PolymarketTrader


class CryptoPolymarketOrchestrator:
    """
    Main orchestration engine for the Crypto Polymarket Trading Agent.

    Execution flow:
    1. Collect signals from all data agents (parallel)
    2. Aggregate signals into weighted composite
    3. Scan Polymarket for relevant markets
    4. For each promising market:
       a. Run swarm analysis (parallel AI queries)
       b. Make trade decision
       c. Execute trade if approved
    5. Log results and wait for next cycle
    """

    def __init__(self, config: Optional[CryptoPolymarketConfig] = None):
        self.config = config or CryptoPolymarketConfig()
        self._init_components()
        self._cycle_count = 0
        self._running = False
        self._pipeline_started = False

    def _init_components(self) -> None:
        """Initialize all sub-components."""
        cprint(
            "\n[START] Initializing Crypto Polymarket Agent v2.1...\n",
            "cyan",
            attrs=["bold"],
        )

        # Initialize the unified data pipeline
        cprint("[PIPELINE] Initializing unified data pipeline...", "cyan")
        self.pipeline = UnifiedDataPipeline()

        # Data Agents (v2.1: All 5 core agents + whale)
        cprint("[AGENTS] Initializing data agents...", "cyan")
        self.liquidation_agent = LiquidationAgent(self.config, pipeline=self.pipeline)
        self.funding_agent = FundingAgent(self.config, pipeline=self.pipeline)
        self.open_interest_agent = OpenInterestAgent(
            self.config, pipeline=self.pipeline
        )
        self.volume_agent = VolumeAgent(self.config, pipeline=self.pipeline)
        self.orderbook_agent = OrderBookImbalanceAgent(
            self.config, pipeline=self.pipeline
        )
        self.whale_agent = WhaleAgent(self.config, pipeline=self.pipeline)

        # Intelligence Components (v2.0: Timeframe + Regime + Edge)
        cprint("[INTEL] Initializing intelligence components...", "cyan")
        self.timeframe_controller = TimeframeController(
            self.config, pipeline=self.pipeline
        )
        self.regime_detector = RegimeDetectionEngine(
            self.config, pipeline=self.pipeline
        )
        self.edge_calculator = EdgeCalculator(self.config)

        # Analysis Components
        cprint("[ANALYSIS] Initializing analysis components...", "cyan")
        self.signal_aggregator = SignalAggregatorV2(self.config)
        self.swarm_analyzer = SwarmAnalyzer(self.config)
        self.decision_engine = DecisionEngine(self.config)

        # Risk Management (v2.0: Circuit breakers) - TODO: Implement in Phase 4
        cprint("[RISK] Initializing risk management...", "cyan")
        # self.risk_manager = RiskManager(self.config)  # Will create in Phase 4

        # Market Integration
        cprint("[MARKET] Initializing market integration...", "cyan")
        self.market_scanner = CryptoMarketScanner(self.config)
        self.trader = PolymarketTrader(self.config)

        # Version info
        cprint(
            f"[OK] Agent v2.1 initialized in {self.config.execution_mode.value.upper()} mode",
            "green",
        )
        cprint(
            f"   Agents: 5 | Timeframes: {len(self.config.timeframes)} | Intelligence: Enabled",
            "green",
        )
        print()

    async def _start_pipeline(self) -> None:
        """Start the data pipeline if not already running."""
        if self._pipeline_started:
            return

        cprint("\n[PLUG] Starting real-time data pipeline...", "cyan")
        cprint("   Connecting to Binance, Bybit, and Hyperliquid...", "white")

        await self.pipeline.start()
        self._pipeline_started = True

        # Wait a moment for initial data to arrive
        cprint("   Waiting for initial data...", "white")
        await asyncio.sleep(3)

        cprint("   [OK] Pipeline connected and receiving data\n", "green")

    async def _stop_pipeline(self) -> None:
        """Stop the data pipeline."""
        if not self._pipeline_started:
            return

        cprint("\n[PLUG] Stopping data pipeline...", "yellow")
        await self.pipeline.stop()
        self._pipeline_started = False
        cprint("   [OK] Pipeline stopped\n", "green")

    async def _collect_multi_timeframe_signals(
        self,
    ) -> Dict[str, Dict[str, MarketSignal]]:
        """
        v2.0: Collect signals from all 4 timeframes and 4 agents in parallel.

        Returns:
            Dict mapping timeframe -> agent_name -> MarketSignal
        """
        if not self.config.enable_multi_timeframe:
            # Fallback to single timeframe
            signals = await self._collect_signals()
            return {"1h": signals}

        cprint("   [TIMER] Queueing multi-timeframe collection...", "white")

        # Prepare tasks for all timeframes and agents
        all_tasks = {}
        for tf_name in self.config.timeframes.keys():
            # Create tasks for each agent in this timeframe
            tasks = {
                f"{tf_name}:liquidation": self.liquidation_agent.get_signal(),
                f"{tf_name}:funding": self.funding_agent.get_signal(),
                f"{tf_name}:open_interest": self.open_interest_agent.get_signal(),
                f"{tf_name}:volume": self.volume_agent.get_signal(),
                f"{tf_name}:orderbook": self.orderbook_agent.get_signal(),
                f"{tf_name}:whale": self.whale_agent.get_signal(),
            }
            all_tasks.update(tasks)

        # Execute all tasks in parallel
        import asyncio

        results = await asyncio.gather(*all_tasks.values(), return_exceptions=True)

        # Organize results by timeframe
        tf_signals = {}
        for key, result in zip(all_tasks.keys(), results):
            tf_name, agent_name = key.split(":")

            if tf_name not in tf_signals:
                tf_signals[tf_name] = {}

            if isinstance(result, Exception):
                cprint(f"      [WARN] {tf_name} {agent_name}: {result}", "yellow")
            else:
                tf_signals[tf_name][agent_name] = result

        # Print summary
        total = sum(len(s) for s in tf_signals.values())
        cprint(
            f"   [TIMER] Collected {total} signals across {len(tf_signals)} timeframes",
            "green",
        )

        return tf_signals

    async def run_cycle(self) -> OrchestratorCycleResult:
        """
        Run a single orchestration cycle.

        Returns:
            OrchestratorCycleResult with all cycle data
        """
        self._cycle_count += 1
        cycle_start = datetime.utcnow()

        cprint(f"\n{'=' * 60}", "cyan")
        cprint(
            f"Starting Cycle #{self._cycle_count} - {cycle_start.strftime('%Y-%m-%d %H:%M:%S')} UTC",
            "cyan",
            attrs=["bold"],
        )
        cprint(f"{'=' * 60}\n", "cyan")

        try:
            # Phase 1: Multi-timeframe signal collection (v2.0)
            cprint("[PIPELINE] Phase 1: Multi-timeframe signal collection", "yellow")
            tf_signals = await self._collect_multi_timeframe_signals()

            if not any(tf_signals.values()):
                cprint("[WARN] No valid signals collected", "yellow")
                return self._create_empty_result(cycle_start)

            # Phase 2: Regime detection
            cprint("\n[INTEL] Phase 2: Detecting market regime", "yellow")
            regime = await self.regime_detector.detect_current_regime()
            cprint(f"   [OK] Current regime: {regime.value.upper()}", "white")

            # Phase 3: Aggregate signals with regime-based weighting
            cprint("\n[ANALYSIS] Phase 3: Routing & aggregating signals", "yellow")

            # Flatten all signals with timeframe weights
            all_signals = {}
            for tf_name, agent_signals in tf_signals.items():
                tf_weight = self.config.timeframe_weights.get(tf_name, 1.0)

                for agent_name, signal in agent_signals.items():
                    composite_key = f"{agent_name}:{tf_name}"
                    all_signals[composite_key] = signal

            # Aggregate with regime weights
            aggregated = self.signal_aggregator.aggregate(all_signals, regime)
            cprint(self.signal_aggregator.get_signal_summary(aggregated), "white")

            # Check if signal is strong enough to proceed
            if aggregated.direction == SignalDirection.NEUTRAL:
                cprint(
                    "[PAUSE]  Neutral signal - skipping trading for this cycle",
                    "yellow",
                )
                return OrchestratorCycleResult(
                    cycle_number=self._cycle_count,
                    timestamp=cycle_start,
                    signals=all_signals,
                    aggregated_signal=aggregated,
                    markets_scanned=[],
                    swarm_results=[],
                    decisions=[],
                    executions=[],
                    cycle_duration=(datetime.utcnow() - cycle_start).total_seconds(),
                )

            # Phase 3: Scan for markets
            cprint(
                "\n[SEARCH] Phase 3: Scanning Polymarket for crypto markets...",
                "yellow",
            )
            markets = self.market_scanner.scan_markets()

            if not markets:
                cprint("[WARN]  No tradeable markets found", "yellow")
                return OrchestratorCycleResult(
                    cycle_number=self._cycle_count,
                    timestamp=cycle_start,
                    signals=all_signals,
                    aggregated_signal=aggregated,
                    markets_scanned=[],
                    swarm_results=[],
                    decisions=[],
                    executions=[],
                    cycle_duration=(datetime.utcnow() - cycle_start).total_seconds(),
                )

            # Rank markets by signal alignment
            ranked_markets = self.market_scanner.rank_markets_by_signal(
                markets, aggregated
            )

            # Phase 4: Analyze top markets with swarm
            cprint("\n[AI] Phase 4: Running swarm analysis on top markets...", "yellow")
            swarm_results = []
            decisions = []
            executions = []

            # Analyze top N markets
            max_markets_to_analyze = min(3, len(ranked_markets))

            for market, alignment_score in ranked_markets[:max_markets_to_analyze]:
                # Quick pre-filter
                opportunity = self.decision_engine.evaluate_market_opportunity(
                    aggregated, market
                )

                if not opportunity["worth_analyzing"]:
                    cprint(
                        f"   [SKIP]  Skipping {market.market_id[:16]}... (low opportunity score)",
                        "white",
                    )
                    continue

                cprint(f"\n   [CHART_UP] Analyzing: {market.question[:60]}...", "cyan")
                cprint(self.market_scanner.get_market_summary(market), "white")

                # Determine if fast mode should be used (for 15-min markets)
                use_fast_mode = False
                if market.end_date and self.config.enable_fast_swarm_mode:
                    hours_left = (market.end_date - datetime.utcnow()).total_seconds() / 3600
                    use_fast_mode = hours_left <= 1.0  # Use fast mode for markets < 1 hour

                # Run swarm analysis (fast mode for short-duration markets)
                swarm_result = await self.swarm_analyzer.analyze(
                    aggregated, market, fast_mode=use_fast_mode
                )
                swarm_results.append(swarm_result)

                cprint(self.swarm_analyzer.get_analysis_summary(swarm_result), "white")

                # v2.0: Calculate edge before making decision
                cprint(
                    "\n   [MONEY] Phase 4b: Calculating edge & Kelly size...", "yellow"
                )
                edge_result = await self._calculate_edge_for_trade(
                    market, aggregated, "1h"
                )

                if not edge_result:
                    cprint(
                        "   [SKIP] Insufficient edge - skipping this market", "yellow"
                    )
                    continue

                # Make decision (v2.0: with edge context)
                decision = self.decision_engine.make_decision(
                    aggregated, market, swarm_result
                )

                # v2.0: Override position size with Kelly sizing
                if decision.should_trade:
                    decision.size_usd = edge_result["position"].bet_size_usd
                    decision.expected_return = (
                        edge_result["edge_data"].expected_value * decision.size_usd
                    )
                    decisions.append(decision)

                    cprint(self.decision_engine.get_decision_summary(decision), "white")
                    cprint(
                        f"   [MONEY] Kelly size: ${decision.size_usd:.0f} "
                        f"(edge: {edge_result['edge_data'].edge_percent:.1f}%)",
                        "green",
                    )

                # v2.0: Execute trade with Kelly size
                if decision.should_trade:
                    execution = self.trader.execute_trade(decision, market)
                    if execution:
                        executions.append(execution)

            # Phase 6: Summary
            cprint(f"\n{'=' * 60}", "green")
            cprint("[CHART] Cycle Summary", "green", attrs=["bold"])
            cprint(f"{'=' * 60}", "green")
            cprint(f"   Regime: {regime.value.upper()}", "white")
            cprint(
                f"   Signals: {sum(len(s) for s in tf_signals.values())} "
                f"(across {len(tf_signals)} timeframes)",
                "white",
            )
            cprint(f"   Markets Analyzed: {len(swarm_results)}", "white")
            cprint(f"   Trade Decisions: {len(decisions)}", "white")
            cprint(f"   Trades Executed: {len(executions)}", "white")

            if decisions:
                total_size = sum(d.size_usd for d in decisions if d.should_trade)
                avg_size = total_size / len([d for d in decisions if d.should_trade])
                cprint(
                    f"   Total Size: ${total_size:.0f} (avg: ${avg_size:.0f})", "white"
                )

            cycle_duration = (datetime.utcnow() - cycle_start).total_seconds()
            cprint(f"   Cycle Duration: {cycle_duration:.1f}s\n", "white")

            result = OrchestratorCycleResult(
                cycle_number=self._cycle_count,
                timestamp=cycle_start,
                signals=tf_signals,
                aggregated_signal=aggregated,
                markets_scanned=markets,
                swarm_results=swarm_results,
                decisions=decisions,
                executions=executions,
                cycle_duration=cycle_duration,
            )

            # Save cycle result
            self._save_cycle_result(result)

            return result

        except Exception as e:
            cprint(f"\n[FAIL] Cycle error: {e}", "red")
            import traceback

            traceback.print_exc()
            return self._create_empty_result(cycle_start)

    async def _collect_signals(self) -> Dict[str, MarketSignal]:
        """
        v2.1: Collect signals from all 6 data agents in parallel.

        Returns:
            Dict mapping agent names to their MarketSignal
        """
        signals = {}

        # Run all 6 agents in parallel (v2.1: 5 core agents + whale)
        cprint("   Collecting signals from 6 agents...", "white")
        tasks = {
            "liquidation": self.liquidation_agent.get_signal(),
            "funding": self.funding_agent.get_signal(),
            "open_interest": self.open_interest_agent.get_signal(),
            "volume": self.volume_agent.get_signal(),
            "orderbook": self.orderbook_agent.get_signal(),
            "whale": self.whale_agent.get_signal(),
        }

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        for agent_name, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                cprint(f"   [WARN]  {agent_name} agent error: {result}", "yellow")
            elif isinstance(result, MarketSignal):
                signals[agent_name] = result
                emoji = (
                    "[BULL]"
                    if result.direction == SignalDirection.BULLISH
                    else "[BEAR]"
                    if result.direction == SignalDirection.BEARISH
                    else "[NEUTRAL]"
                )
                cprint(
                    f"   {emoji} {agent_name}: {result.direction.value} ({result.confidence:.0%})",
                    "white",
                )

        cprint(f"   [OK] Collected {len(signals)} valid signals", "green")
        return signals

    def _calculate_time_to_event(self, market: CryptoMarket) -> float:
        """Calculate hours until market resolution."""
        if not market.end_date:
            return 168.0  # Default to 1 week

        now = datetime.utcnow()
        time_diff = market.end_date - now
        return max(0.0, time_diff.total_seconds() / 3600.0)

    def _signal_to_probability(self, signal: AggregatedSignal) -> float:
        """Convert signal to win probability estimate (0-1)."""
        base_prob = 0.5  # Start neutral

        if signal.direction == SignalDirection.BULLISH:
            base_prob += signal.composite_score * signal.confidence * 0.5
        elif signal.direction == SignalDirection.BEARISH:
            base_prob -= abs(signal.composite_score) * signal.confidence * 0.5

        return max(0.01, min(0.99, base_prob))  # Clip to valid range

    async def _calculate_edge_for_trade(
        self, market: CryptoMarket, signal: AggregatedSignal, timeframe: str = "1h"
    ) -> Optional[Dict[str, Any]]:
        """
        v2.0: Calculate edge and Kelly-optimal position size.

        Returns:
            Dict with edge_data and position, or None if insufficient edge
        """
        try:
            # Get market price (midpoint)
            if not market.best_bid or not market.best_ask:
                return None

            market_price = (
                (market.best_bid + market.best_ask) / 2 / 100
            )  # Convert to decimal

            # Calculate signal probability
            signal_prob = self._signal_to_probability(signal)

            # Calculate edge
            edge_data = self.edge_calculator.calculate_edge(
                signal_probability=signal_prob,
                market_probability=market_price,
                signal_confidence=signal.confidence,
                hours_until_resolution=self._calculate_time_to_event(market),
                signal_strength=abs(signal.composite_score),
            )

            # Check minimum edge threshold
            if edge_data.edge_percent < self.config.min_edge_threshold:
                cprint(
                    f"   [EDGE] Edge too low: {edge_data.edge_percent:.1f}% "
                    f"(min: {self.config.min_edge_threshold:.1f}%)",
                    "yellow",
                )
                return None

            # Calculate Kelly position size
            position = self.edge_calculator.calculate_position_size(
                edge=edge_data.edge_percent / 100,
                market_prob=market_price,
                confidence=signal.confidence,
                total_capital=25000.0,  # TODO: Get from portfolio/account
                timeframe=timeframe,
            )

            cprint(
                f"   [EDGE] Edge: {edge_data.edge_percent:.1f}% | "
                f"Kelly: {position.kelly_fraction:.1%} | "
                f"Size: ${position.bet_size_usd:.0f}",
                "green",
            )

            return {
                "edge_data": edge_data,
                "position": position,
                "meets_threshold": True,
            }

        except Exception as e:
            cprint(f"   [WARN] Edge calculation error: {e}", "yellow")
            return None

    def _create_empty_result(self, start_time: datetime) -> OrchestratorCycleResult:
        """Create an empty cycle result."""
        return OrchestratorCycleResult(
            cycle_number=self._cycle_count,
            timestamp=start_time,
            signals={},
            aggregated_signal=None,
            markets_scanned=[],
            swarm_results=[],
            decisions=[],
            executions=[],
            cycle_duration=(datetime.utcnow() - start_time).total_seconds(),
        )

    def _save_cycle_result(self, result: OrchestratorCycleResult) -> None:
        """Save cycle result to disk."""
        try:
            save_dir = self.config.data_dir / "cycles"
            save_dir.mkdir(parents=True, exist_ok=True)

            filename = f"cycle_{result.cycle_number}_{result.timestamp.strftime('%Y%m%d_%H%M%S')}.json"

            data = {
                "cycle_number": result.cycle_number,
                "timestamp": result.timestamp.isoformat(),
                "cycle_duration": result.cycle_duration,
                "signal_count": len(result.signals),
                "markets_scanned": len(result.markets_scanned),
                "swarm_analyses": len(result.swarm_results),
                "decisions": len(result.decisions),
                "executions": len(result.executions),
            }

            if result.aggregated_signal:
                data["aggregated_signal"] = {
                    "direction": result.aggregated_signal.direction.value,
                    "composite_score": result.aggregated_signal.composite_score,
                    "confidence": result.aggregated_signal.confidence,
                }

            with open(save_dir / filename, "w") as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            cprint(f"Error saving cycle result: {e}", "red")

    async def run(self, cycles: int = 0) -> None:
        """
        Run the orchestrator.

        Args:
            cycles: Number of cycles to run (0 = infinite)
        """
        self._running = True
        cycles_completed = 0

        cprint("\n" + "=" * 60, "magenta")
        cprint("MOON CRYPTO POLYMARKET AGENT STARTED", "magenta", attrs=["bold"])
        cprint(f"   Mode: {self.config.execution_mode.value.upper()}", "magenta")
        cprint(f"   Cycle Interval: {self.config.cycle_interval_seconds}s", "magenta")
        cprint("=" * 60 + "\n", "magenta")

        try:
            # Start the data pipeline
            await self._start_pipeline()

            while self._running:
                await self.run_cycle()
                cycles_completed += 1

                # Check if we should stop
                if cycles > 0 and cycles_completed >= cycles:
                    cprint(f"\n[OK] Completed {cycles_completed} cycles", "green")
                    break

                # Wait for next cycle
                cprint(
                    f"\n[TIME] Next cycle in {self.config.cycle_interval_seconds} seconds...\n",
                    "cyan",
                )
                await asyncio.sleep(self.config.cycle_interval_seconds)

        except KeyboardInterrupt:
            cprint(
                "\n\n[STOP] Received interrupt - shutting down gracefully...", "yellow"
            )

        except Exception as e:
            cprint(f"\n[FAIL] Fatal error: {e}", "red")
            import traceback

            traceback.print_exc()

        finally:
            self._running = False
            await self._stop_pipeline()
            cprint("\nAgent stopped\n", "magenta")

    def stop(self) -> None:
        """Stop the orchestrator gracefully."""
        self._running = False

    def get_status(self) -> Dict[str, Any]:
        """Get current agent status."""
        status = {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "execution_mode": self.config.execution_mode.value,
            "pipeline_started": self._pipeline_started,
            "positions": self.trader.position_tracker.get_risk_status(),
            "trading_stats": self.trader.get_trading_stats(),
        }

        # Add pipeline stats if available
        if self._pipeline_started:
            status["pipeline_stats"] = self.pipeline.get_stats()

        return status

    def print_status(self) -> None:
        """Print current agent status."""
        status = self.get_status()

        cprint("\n" + "=" * 60, "cyan")
        cprint("[CHART] AGENT STATUS", "cyan", attrs=["bold"])
        cprint("=" * 60, "cyan")

        cprint(f"\nRunning: {'Yes' if status['running'] else 'No'}", "white")
        cprint(f"Cycles Completed: {status['cycle_count']}", "white")
        cprint(f"Mode: {status['execution_mode'].upper()}", "white")
        cprint(
            f"Pipeline: {'Connected' if status['pipeline_started'] else 'Not Started'}",
            "white",
        )

        # Show pipeline stats if available
        if status.get("pipeline_stats"):
            cprint("\n[PIPELINE] Pipeline Stats:", "yellow")
            ps = status["pipeline_stats"]
            cprint(f"   Liquidations: {ps.get('liquidation_count', 0)}", "white")
            cprint(f"   Trades: {ps.get('trade_count', 0)}", "white")
            cprint(f"   Order Books: {ps.get('orderbook_count', 0)}", "white")

        cprint("\n[CHART_UP] Positions:", "yellow")
        pos_status = status["positions"]
        cprint(f"   Total Exposure: ${pos_status['total_exposure']:,.2f}", "white")
        cprint(f"   Utilization: {pos_status['exposure_utilization']:.1%}", "white")
        cprint(f"   Unrealized PnL: ${pos_status['unrealized_pnl']:+,.2f}", "white")

        cprint("\n[CHART] Trading Stats:", "yellow")
        stats = status["trading_stats"]
        cprint(f"   Total Trades: {stats['total_trades']}", "white")
        cprint(f"   Total Volume: ${stats['total_volume']:,.2f}", "white")

        cprint("\n" + "=" * 60 + "\n", "cyan")


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Crypto Polymarket Trading Agent")
    parser.add_argument(
        "--mode",
        choices=["dry_run", "paper", "live"],
        default="dry_run",
        help="Execution mode",
    )
    parser.add_argument(
        "--cycles", type=int, default=0, help="Number of cycles (0 = infinite)"
    )
    parser.add_argument(
        "--interval", type=int, default=300, help="Cycle interval in seconds"
    )
    parser.add_argument("--status", action="store_true", help="Print status and exit")

    args = parser.parse_args()

    # Create config with command line overrides
    config = CryptoPolymarketConfig(
        execution_mode=ExecutionMode(args.mode),
        cycle_interval_seconds=args.interval,
    )

    orchestrator = CryptoPolymarketOrchestrator(config)

    if args.status:
        orchestrator.print_status()
        return

    await orchestrator.run(cycles=args.cycles)


if __name__ == "__main__":
    asyncio.run(main())
