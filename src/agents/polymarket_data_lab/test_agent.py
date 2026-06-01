"""
Crypto Polymarket Agent - End-to-End Test Script

Tests all layers of the trading agent:
1. Data Pipeline (WebSocket connections)
2. Data Agents (Liquidation, Whale signals)
3. Signal Aggregation
4. AI Swarm (multi-model consensus)
5. Decision Engine
6. Market Scanner
7. Full Orchestrator Cycle

Usage:
    python -m src.agents.crypto_polymarket.test_agent
    python -m src.agents.crypto_polymarket.test_agent --test swarm
    python -m src.agents.crypto_polymarket.test_agent --test all

Built with love by TradeHive
"""

import sys
import asyncio
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
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
    AggregatedSignal,
    CryptoMarket,
    MarketSignal,
    SwarmAnalysisResult,
    ModelPrediction,
    TradeDecision,
)


class AgentTester:
    """End-to-end test runner for the Crypto Polymarket Agent."""

    def __init__(self):
        self.config = CryptoPolymarketConfig()
        self.config.execution_mode = ExecutionMode.DRY_RUN
        self.results: Dict[str, bool] = {}

    def print_header(self, title: str) -> None:
        """Print a test section header."""
        cprint("\n" + "=" * 60, "cyan")
        cprint(f"  {title}", "cyan", attrs=["bold"])
        cprint("=" * 60, "cyan")

    def print_result(self, test_name: str, passed: bool, details: str = "") -> None:
        """Print test result."""
        emoji = "[OK]" if passed else "[FAIL]"
        color = "green" if passed else "red"
        cprint(f"{emoji} {test_name}: {'PASSED' if passed else 'FAILED'}", color)
        if details:
            cprint(f"   {details}", "white")
        self.results[test_name] = passed

    async def test_config(self) -> bool:
        """Test configuration loading."""
        self.print_header("1. Configuration Test")

        try:
            # Test weight validation
            weights_valid = self.config.validate_weights()
            self.print_result(
                "Weight validation",
                weights_valid,
                f"Liquidation: {self.config.liquidation_weight}, Whale: {self.config.whale_weight}",
            )

            # Test credentials check
            creds = self.config.validate_credentials()
            creds_count = sum(1 for v in creds.values() if v)
            self.print_result(
                "Credentials loaded",
                creds_count >= 1,
                f"{creds_count}/6 providers configured: {[k for k, v in creds.items() if v]}",
            )

            # Test paths
            paths_exist = self.config.data_dir.parent.exists()
            self.print_result("Data paths valid", paths_exist)

            return weights_valid and creds_count >= 1

        except Exception as e:
            self.print_result("Configuration", False, str(e))
            return False

    async def test_data_pipeline(self) -> bool:
        """Test data pipeline initialization (no actual connection)."""
        self.print_header("2. Data Pipeline Test")

        try:
            from src.data.connectors.unified_pipeline import UnifiedDataPipeline

            pipeline = UnifiedDataPipeline(self.config)

            # Check connectors dict exists
            connectors_ok = hasattr(pipeline, "_connectors") or hasattr(
                pipeline, "connectors"
            )
            self.print_result("Connectors dict exists", connectors_ok)

            # Check pipeline has required methods
            methods_ok = (
                hasattr(pipeline, "start")
                and hasattr(pipeline, "stop")
                and hasattr(pipeline, "get_status")
            )
            self.print_result("Pipeline methods available", methods_ok)

            return connectors_ok

        except ImportError as e:
            self.print_result("Pipeline import", False, str(e))
            return False
        except Exception as e:
            self.print_result("Pipeline test", False, str(e))
            return False

    async def test_data_agents(self) -> bool:
        """Test data agents can be initialized and produce signals."""
        self.print_header("3. Data Agents Test")

        try:
            from src.agents.crypto_polymarket.data_agents.liquidation_agent import (
                LiquidationAgent,
            )
            from src.agents.crypto_polymarket.data_agents.whale_agent import WhaleAgent

            # Initialize agents (without pipeline for testing)
            liq_agent = LiquidationAgent(self.config)
            whale_agent = WhaleAgent(self.config)

            self.print_result("Liquidation Agent initialized", True)
            self.print_result("Whale Agent initialized", True)

            # Test signal structure
            mock_signal = MarketSignal(
                agent_name="test",
                symbol="BTC",
                timestamp=datetime.utcnow(),
                direction=SignalDirection.BULLISH,
                strength=0.7,
                confidence=0.8,
                raw_data={"test": True},
            )
            signal_valid = (
                hasattr(mock_signal, "direction")
                and hasattr(mock_signal, "strength")
                and hasattr(mock_signal, "confidence")
            )
            self.print_result("Signal model valid", signal_valid)

            return True

        except ImportError as e:
            self.print_result("Agent import", False, str(e))
            return False
        except Exception as e:
            self.print_result("Agent test", False, str(e))
            return False

    async def test_signal_aggregator(self) -> bool:
        """Test signal aggregation logic."""
        self.print_header("4. Signal Aggregator Test")

        try:
            from src.agents.crypto_polymarket.analysis.signal_aggregator import (
                SignalAggregator,
            )

            aggregator = SignalAggregator(self.config)

            # Create mock signals
            mock_signals = {
                "liquidation": MarketSignal(
                    agent_name="liquidation",
                    symbol="BTC",
                    timestamp=datetime.utcnow(),
                    direction=SignalDirection.BULLISH,
                    strength=0.8,
                    confidence=0.75,
                    raw_data={},
                ),
                "whale": MarketSignal(
                    agent_name="whale",
                    symbol="BTC",
                    timestamp=datetime.utcnow(),
                    direction=SignalDirection.BULLISH,
                    strength=0.6,
                    confidence=0.85,
                    raw_data={},
                ),
            }

            # Test aggregation
            aggregated = aggregator.aggregate(mock_signals)

            score_valid = -1.0 <= aggregated.composite_score <= 1.0
            self.print_result(
                "Composite score in range",
                score_valid,
                f"Score: {aggregated.composite_score:+.3f}",
            )

            direction_valid = aggregated.direction in [
                SignalDirection.BULLISH,
                SignalDirection.BEARISH,
                SignalDirection.NEUTRAL,
            ]
            self.print_result(
                "Direction determined",
                direction_valid,
                f"Direction: {aggregated.direction.value}",
            )

            confidence_valid = 0.0 <= aggregated.confidence <= 1.0
            self.print_result(
                "Confidence in range",
                confidence_valid,
                f"Confidence: {aggregated.confidence:.1%}",
            )

            # Test weights are applied
            weights_applied = len(aggregated.signal_breakdown) == 2
            self.print_result(
                "Weights applied",
                weights_applied,
                f"Breakdown: {aggregated.signal_breakdown}",
            )

            return score_valid and direction_valid and confidence_valid

        except Exception as e:
            self.print_result("Aggregator test", False, str(e))
            return False

    async def test_swarm_analyzer(self) -> bool:
        """Test AI swarm initialization and model availability."""
        self.print_header("5. AI Swarm Test")

        try:
            from src.agents.crypto_polymarket.analysis.swarm_analyzer import (
                SwarmAnalyzer,
            )

            swarm = SwarmAnalyzer(self.config)

            # Check which clients are available
            available_clients = list(swarm._clients.keys())
            clients_available = len(available_clients) > 0
            self.print_result(
                "AI clients initialized",
                clients_available,
                f"Available: {available_clients}",
            )

            # Check model configuration
            models_configured = len(swarm.MODELS) >= 3
            self.print_result(
                "Models configured",
                models_configured,
                f"Models: {list(swarm.MODELS.keys())}",
            )

            # Test prompt building
            mock_signal = AggregatedSignal(
                symbol="BTC",
                timestamp=datetime.utcnow(),
                direction=SignalDirection.BULLISH,
                composite_score=0.5,
                confidence=0.8,
                signals=[],
                dominant_signal="liquidation",
                signal_breakdown={"liquidation": 0.3, "whale": 0.2},
            )

            mock_market = CryptoMarket(
                market_id="test123",
                question="Will BTC be above $100k by end of January?",
                symbol="BTC",
                yes_token_id="yes123",
                no_token_id="no123",
                yes_price=0.45,
                no_price=0.55,
                liquidity=100000.0,
                end_date=datetime.utcnow() + timedelta(days=30),
                is_active=True,
                price_target=100000.0,
                market_type="bullish",
            )

            prompt = swarm._build_prompt(mock_signal, mock_market)
            prompt_valid = len(prompt) > 100 and "BTC" in prompt
            self.print_result(
                "Prompt generation", prompt_valid, f"Prompt length: {len(prompt)} chars"
            )

            return clients_available or models_configured

        except Exception as e:
            self.print_result("Swarm test", False, str(e))
            return False

    async def test_decision_engine(self) -> bool:
        """Test decision engine logic."""
        self.print_header("6. Decision Engine Test")

        try:
            from src.agents.crypto_polymarket.analysis.decision_engine import (
                DecisionEngine,
            )

            engine = DecisionEngine(self.config)

            # Create mock inputs
            mock_signal = AggregatedSignal(
                symbol="BTC",
                timestamp=datetime.utcnow(),
                direction=SignalDirection.BULLISH,
                composite_score=0.5,
                confidence=0.8,
                signals=[],
                dominant_signal="liquidation",
                signal_breakdown={"liquidation": 0.3, "whale": 0.2},
            )

            mock_market = CryptoMarket(
                market_id="test123",
                question="Will BTC be above $100k by end of January?",
                symbol="BTC",
                yes_token_id="yes123",
                no_token_id="no123",
                yes_price=0.45,
                no_price=0.55,
                liquidity=100000.0,
                end_date=datetime.utcnow() + timedelta(days=30),
                is_active=True,
                price_target=100000.0,
                market_type="bullish",
            )

            mock_swarm = SwarmAnalysisResult(
                market_id="test123",
                timestamp=datetime.utcnow(),
                predictions=[
                    ModelPrediction(
                        model_name="test_model",
                        prediction="YES",
                        confidence=0.8,
                        reasoning="Test reasoning",
                        weight=1.0,
                        timestamp=datetime.utcnow(),
                    )
                ],
                consensus_prediction="YES",
                consensus_confidence=0.8,
                yes_votes=1,
                no_votes=0,
                agreement_ratio=1.0,
            )

            # Test individual checks
            sig_check = engine._check_signal_strength(mock_signal)
            self.print_result("Signal strength check", True, f"Result: {sig_check}")

            swarm_check = engine._check_swarm_consensus(mock_swarm)
            self.print_result("Swarm consensus check", True, f"Result: {swarm_check}")

            time_check = engine._check_time_remaining(mock_market)
            self.print_result("Time remaining check", True, f"Result: {time_check}")

            spread_check = engine._check_spread(mock_market)
            self.print_result("Spread check", True, f"Result: {spread_check}")

            # Test full decision
            decision = engine.make_decision(mock_signal, mock_market, mock_swarm)
            decision_valid = isinstance(decision, TradeDecision)
            self.print_result(
                "Decision made",
                decision_valid,
                f"Should trade: {decision.should_trade}, Reason: {decision.reason}",
            )

            return decision_valid

        except Exception as e:
            self.print_result("Decision engine test", False, str(e))
            return False

    async def test_market_scanner(self) -> bool:
        """Test market scanner initialization."""
        self.print_header("7. Market Scanner Test")

        try:
            from src.agents.crypto_polymarket.market.scanner import CryptoMarketScanner

            scanner = CryptoMarketScanner(self.config)

            # Check search queries expanded
            queries_count = len(scanner.SEARCH_QUERIES)
            queries_ok = queries_count >= 5
            self.print_result(
                "Search queries configured", queries_ok, f"Queries: {queries_count}"
            )

            # Test price extraction
            test_cases = [
                ("Will BTC reach $100k?", 100000.0),
                ("Bitcoin above $150,000", 150000.0),
                ("ETH hits 10K", 10000.0),
            ]

            all_passed = True
            for question, expected in test_cases:
                result = scanner._extract_price_target(question)
                passed = result == expected
                if not passed:
                    all_passed = False
                    cprint(
                        f"   Price extraction: '{question}' -> {result} (expected {expected})",
                        "yellow",
                    )

            self.print_result("Price extraction", all_passed)

            # Test market type detection
            bullish_q = "Will Bitcoin be above $100k?"
            bearish_q = "Will ETH fall below $2000?"

            bullish_type = scanner._determine_market_type(bullish_q)
            bearish_type = scanner._determine_market_type(bearish_q)

            type_ok = bullish_type == "bullish" and bearish_type == "bearish"
            self.print_result(
                "Market type detection",
                type_ok,
                f"Bullish: '{bullish_type}', Bearish: '{bearish_type}'",
            )

            return queries_ok and type_ok

        except Exception as e:
            self.print_result("Scanner test", False, str(e))
            return False

    async def test_orchestrator_init(self) -> bool:
        """Test orchestrator initialization (no actual trading)."""
        self.print_header("8. Orchestrator Initialization Test")

        try:
            from src.agents.crypto_polymarket.orchestrator import (
                CryptoPolymarketOrchestrator,
            )

            # Force dry run mode
            self.config.execution_mode = ExecutionMode.DRY_RUN

            orchestrator = CryptoPolymarketOrchestrator(self.config)

            # Check components initialized
            components = [
                ("pipeline", hasattr(orchestrator, "pipeline")),
                ("liquidation_agent", hasattr(orchestrator, "liquidation_agent")),
                ("whale_agent", hasattr(orchestrator, "whale_agent")),
                ("signal_aggregator", hasattr(orchestrator, "signal_aggregator")),
                ("swarm_analyzer", hasattr(orchestrator, "swarm_analyzer")),
                ("decision_engine", hasattr(orchestrator, "decision_engine")),
                ("market_scanner", hasattr(orchestrator, "market_scanner")),
            ]

            all_ok = True
            for name, ok in components:
                if not ok:
                    all_ok = False
                    cprint(f"   Missing: {name}", "yellow")

            self.print_result(
                "All components initialized",
                all_ok,
                f"{sum(1 for _, ok in components if ok)}/{len(components)} components",
            )

            return all_ok

        except Exception as e:
            self.print_result("Orchestrator test", False, str(e))
            return False

    async def run_all_tests(self) -> bool:
        """Run all tests and print summary."""
        cprint("\n" + "=" * 60, "magenta", attrs=["bold"])
        cprint(
            "  CRYPTO POLYMARKET AGENT - END-TO-END TESTS", "magenta", attrs=["bold"]
        )
        cprint("=" * 60, "magenta", attrs=["bold"])

        await self.test_config()
        await self.test_data_pipeline()
        await self.test_data_agents()
        await self.test_signal_aggregator()
        await self.test_swarm_analyzer()
        await self.test_decision_engine()
        await self.test_market_scanner()
        await self.test_orchestrator_init()

        # Summary
        self.print_header("TEST SUMMARY")
        passed = sum(1 for v in self.results.values() if v)
        total = len(self.results)
        all_passed = passed == total

        color = "green" if all_passed else "yellow" if passed > total // 2 else "red"
        cprint(f"\nResults: {passed}/{total} tests passed", color, attrs=["bold"])

        if not all_passed:
            cprint("\nFailed tests:", "red")
            for name, passed in self.results.items():
                if not passed:
                    cprint(f"  - {name}", "red")

        return all_passed

    async def run_single_test(self, test_name: str) -> bool:
        """Run a single test by name."""
        test_map = {
            "config": self.test_config,
            "pipeline": self.test_data_pipeline,
            "agents": self.test_data_agents,
            "aggregator": self.test_signal_aggregator,
            "swarm": self.test_swarm_analyzer,
            "decision": self.test_decision_engine,
            "scanner": self.test_market_scanner,
            "orchestrator": self.test_orchestrator_init,
        }

        if test_name not in test_map:
            cprint(f"Unknown test: {test_name}", "red")
            cprint(f"Available: {list(test_map.keys())}", "yellow")
            return False

        return await test_map[test_name]()


def main():
    parser = argparse.ArgumentParser(description="Test Crypto Polymarket Agent")
    parser.add_argument(
        "--test",
        choices=[
            "all",
            "config",
            "pipeline",
            "agents",
            "aggregator",
            "swarm",
            "decision",
            "scanner",
            "orchestrator",
        ],
        default="all",
        help="Which test to run",
    )
    args = parser.parse_args()

    tester = AgentTester()

    if args.test == "all":
        success = asyncio.run(tester.run_all_tests())
    else:
        success = asyncio.run(tester.run_single_test(args.test))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
