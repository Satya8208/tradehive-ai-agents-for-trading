"""
v2.0 Orchestrator with multi-timeframe support
Extended functionality without breaking existing code
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def add_timeframe_methods(orchestrator_class):
    """
    Decorator/mixin to add v2.0 methods to orchestrator without modifying original
    """

    # Store original methods
    original_init = orchestrator_class.__init__
    original_collect = orchestrator_class._collect_signals

    def new_init(self, config=None):
        # Call original
        original_init(self, config)

        # Add v2.0 tracking
        self._signal_cache = {}  # Cache for timeframe signals

    async def collect_multi_timeframe_signals(self) -> Dict[str, Dict[str, Any]]:
        """
        v2.0: Collect signals from all timeframes and agents in parallel.

        Returns:
            {
                "15m": {"liquidation": signal, "funding": signal, ...},
                "30m": {...},
                "1h": {...},
                "4h": {...}
            }
        """
        if not self.config.enable_multi_timeframe:
            # Fallback to single timeframe
            base_signals = await original_collect(self)
            return {"1h": base_signals}

        print("[TIMER] Collecting multi-timeframe signals...")

        # Collect signals for each timeframe in parallel
        timeframe_tasks = {}
        for tf_name in self.config.timeframes.keys():
            print(f"   [TIMER] Collecting {tf_name} signals...")

            # Collect all 5 agents for this timeframe
            agent_tasks = {
                "liquidation": self._get_agent_signal("liquidation", tf_name),
                "funding": self._get_agent_signal("funding", tf_name),
                "open_interest": self._get_agent_signal("open_interest", tf_name),
                "volume": self._get_agent_signal("volume", tf_name),
                "whale": self._get_agent_signal("whale", tf_name),
            }
            timeframe_tasks[tf_name] = agent_tasks

        # Execute all collections in parallel
        all_results = {}
        import asyncio

        for tf_name, agent_tasks in timeframe_tasks.items():
            results = await asyncio.gather(
                *agent_tasks.values(), return_exceptions=True
            )

            tf_signals = {}
            for agent_name, result in zip(agent_tasks.keys(), results):
                if isinstance(result, Exception):
                    print(f"   [WARN] {tf_name} {agent_name} error: {result}")
                else:
                    tf_signals[agent_name] = result

            all_results[tf_name] = tf_signals
            print(f"   [OK] {tf_name}: {len(tf_signals)} signals collected")

        return all_results

    async def _get_agent_signal(self, agent_name: str, timeframe: str):
        """Helper to get signal from specific agent with timeframe context"""
        agent = getattr(self, f"{agent_name}_agent")

        # v2.0: Call agent's get_signal but pass timeframe via cache
        # For now, agents don't take timeframe param, so just call normally
        # Future: agent.get_signal(timeframe=timeframe)
        if hasattr(agent, "get_signal"):
            return await agent.get_signal()
        else:
            return agent.get_signal_sync()

    def calculate_edge_for_market(self, market, signal, timeframe="1h"):
        """v2.0: Calculate edge for a market"""
        # This will be implemented with edge calculator
        pass

    # Apply the extensions
    orchestrator_class.__init__ = new_init
    orchestrator_class.collect_multi_timeframe_signals = collect_multi_timeframe_signals
    orchestrator_class.calculate_edge_for_market = calculate_edge_for_market

    return orchestrator_class


# Example usage:
# from src.agents.crypto_polymarket.orchestrator import CryptoPolymarketOrchestrator
# CryptoPolymarketOrchestrator = add_timeframe_methods(CryptoPolymarketOrchestrator)
