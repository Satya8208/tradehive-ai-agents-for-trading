"""
Timeframe Controller for Crypto Polymarket Agent

Manages multi-timeframe signal generation and routing.
Each timeframe runs independent analysis with appropriate lookback periods.

Design Philosophy:
- 15m: Fast signals for hourly/daily events
- 30m: Balanced signals for 2-7 day events
- 1h: Strong signals for weekly events
- 4h: High-conviction signals for monthly events

Each timeframe generates independent signals that are then weighted by
event time-to-resolution.

Built with love by TradeHive
"""

import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass
from termcolor import cprint

import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.config import CryptoPolymarketConfig
from src.agents.crypto_polymarket.data_agents.liquidation_agent import LiquidationAgent
from src.agents.crypto_polymarket.data_agents.funding_agent import FundingAgent
from src.agents.crypto_polymarket.data_agents.open_interest_agent import (
    OpenInterestAgent,
)
from src.agents.crypto_polymarket.data_agents.volume_agent import VolumeAgent
from src.agents.crypto_polymarket.models import MarketSignal, TimeframeSignalBundle
from src.data.connectors.unified_pipeline import UnifiedDataPipeline


@dataclass
class TimeframeSignals:
    """Container for all signals at a specific timeframe"""

    timeframe: str  # "15m", "30m", "1h", "4h"
    window_seconds: int
    liquidation: Optional[MarketSignal] = None
    funding: Optional[MarketSignal] = None
    open_interest: Optional[MarketSignal] = None
    volume: Optional[MarketSignal] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()

    def get_all_signals(self) -> List[MarketSignal]:
        """Get all non-None signals for aggregation."""
        signals = []
        for signal in [self.liquidation, self.funding, self.open_interest, self.volume]:
            if signal is not None:
                signals.append(signal)
        return signals

    def get_signal_summary(self) -> str:
        """Get human-readable summary of signals."""
        signals = self.get_all_signals()
        if not signals:
            return f"{self.timeframe}: No signals"

        summary = f"\n{self.timeframe} ({self.window_seconds // 60}min) Signals:\n"
        summary += "=" * 50 + "\n"

        for signal in signals:
            emoji = (
                "[BULL]"
                if signal.direction.value == "bullish"
                else "[BEAR]"
                if signal.direction.value == "bearish"
                else "[NEUTRAL]"
            )
            summary += f"  {emoji} {signal.agent_name:15} {signal.direction.value:10} (strength: {signal.strength:.2f}, confidence: {signal.confidence:.2f})\n"
            summary += f"      └─ {signal.reasoning}\n"

        return summary


class TimeframeController:
    """
    Manages multi-timeframe signal generation and routing.

    Each timeframe runs parallel data collection and analysis,
    then aggregates signals based on event time-to-resolution.
    """

    def __init__(self, config: CryptoPolymarketConfig, pipeline: UnifiedDataPipeline):
        """
        Initialize timeframe controller.

        Args:
            config: Agent configuration with timeframe settings
            pipeline: Unified data pipeline for all agents
        """
        self.config = config
        self.pipeline = pipeline
        self.timeframes: Dict[str, int] = config.timeframes

        # Initialize agents for each timeframe
        # v2.0 Simplified: Agents are created by orchestrator, not here
        # For Phase 1, we use single timeframe. Multi-timeframe comes in Phase 3
        self.agents: Dict[str, Dict[str, Any]] = {}

        # Create empty structure for backward compatibility
        for timeframe in self.timeframes.keys():
            self.agents[timeframe] = {}

        cprint(
            f"[OK] Timeframe Controller initialized for {len(self.timeframes)} timeframes",
            "cyan",
        )

    async def collect_all_signals(self) -> Dict[str, TimeframeSignals]:
        """
        Collect signals from all timeframes in parallel.

        This is the main entry point - runs all agents across all timeframes
        simultaneously for maximum efficiency.

        Returns:
            Dict mapping timeframe to TimeframeSignals container
        """
        # Build all tasks for parallel execution
        tasks = []
        task_metadata = []  # Store which timeframe and agent each task corresponds to

        for timeframe, timeframe_agents in self.agents.items():
            window_seconds = self.timeframes[timeframe]

            for agent_name, agent in timeframe_agents.items():
                # Create task for this agent at this timeframe
                task = asyncio.create_task(agent.get_signal())
                tasks.append(task)
                task_metadata.append(
                    {
                        "timeframe": timeframe,
                        "window": window_seconds,
                        "agent_name": agent_name,
                    }
                )

        # Execute all tasks in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Organize results by timeframe
        timeframe_signals: Dict[str, TimeframeSignals] = {}

        for i, result in enumerate(results):
            metadata = task_metadata[i]
            timeframe = metadata["timeframe"]

            # Initialize container if needed
            if timeframe not in timeframe_signals:
                timeframe_signals[timeframe] = TimeframeSignals(
                    timeframe=timeframe, window_seconds=metadata["window"]
                )

            # Handle errors
            if isinstance(result, Exception):
                cprint(
                    f"[WARN]  Signal error [{timeframe}][{metadata['agent_name']}]: {str(result)}",
                    "yellow",
                )
                continue

            # Store signal
            signal = result
            if signal:
                setattr(timeframe_signals[timeframe], metadata["agent_name"], signal)

        # Log summary
        total_signals = sum(
            len(ts.get_all_signals()) for ts in timeframe_signals.values()
        )
        cprint(
            f"[CHART] Collected {total_signals} signals across {len(timeframe_signals)} timeframes",
            "green",
        )

        # Print detailed summary
        for timeframe, signals in timeframe_signals.items():
            cprint(signals.get_signal_summary(), "white")

        return timeframe_signals

    def get_weighted_composite_score(
        self,
        timeframe_signals: Dict[str, TimeframeSignals],
        event_hours_until_resolution: float,
    ) -> Dict[str, Any]:
        """
        Calculate composite score weighted by timeframe and event duration.

        Core Logic:
        - Short events (< 6h): Weight 15m/30m signals heavily
        - Medium events (6h-48h): Balanced weight across all timeframes
        - Long events (> 48h): Weight 1h/4h signals heavily

        Args:
            timeframe_signals: Signals from collect_all_signals()
            event_hours_until_resolution: Hours until Polymarket event resolves

        Returns:
            Dict with {
                "composite_score": float (-1 to 1),
                "direction": SignalDirection,
                "confidence": float (0 to 1),
                "contributing_timeframes": List[str],
                "weight_breakdown": Dict,
                "reasoning": str
            }
        """
        # Determine timeframe weights based on event duration
        timeframe_contributions: Dict[str, float] = {}

        # ULTRA-SHORT EVENTS (<= 30 minutes): Heavy weight on 15m for 15-min market trading
        if event_hours_until_resolution <= 0.5:
            timeframe_contributions = {
                "15m": 0.85,  # 85% weight on 15m (primary signal)
                "30m": 0.15,  # 15% weight on 30m (confirmation)
                "1h": 0.00,  # 0% weight on 1h (too slow)
                "4h": 0.00,  # 0% weight on 4h (too slow)
            }

        # SHORT EVENTS (30 min - 6 hours): Heavy weight on 15m
        elif event_hours_until_resolution <= 6:
            timeframe_contributions = {
                "15m": 0.60,  # 60% weight on 15m
                "30m": 0.30,  # 30% weight on 30m
                "1h": 0.10,  # 10% weight on 1h
                "4h": 0.00,  # 0% weight on 4h (too slow)
            }

        # MEDIUM EVENTS (6-48 hours): Balanced across all
        elif event_hours_until_resolution <= 48:
            timeframe_contributions = {
                "15m": 0.25,  # 25% weight on 15m
                "30m": 0.30,  # 30% weight on 30m
                "1h": 0.30,  # 30% weight on 1h
                "4h": 0.15,  # 15% weight on 4h
            }

        # LONG EVENTS (> 48 hours): Heavy weight on longer timeframes
        else:
            timeframe_contributions = {
                "15m": 0.10,  # 10% weight on 15m (too noisy for long events)
                "30m": 0.20,  # 20% weight on 30m
                "1h": 0.35,  # 35% weight on 1h
                "4h": 0.35,  # 35% weight on 4h (most reliable for long events)
            }

        # Apply timeframe-specific signal weights from config
        timeframe_signal_weights = self.config.timeframe_weights

        # Calculate weighted composite score
        total_score = 0.0
        total_weight = 0.0
        contributing_signals = 0

        weight_breakdown = {}

        for timeframe, signals in timeframe_signals.items():
            # Get all signals for this timeframe
            individual_signals = signals.get_all_signals()

            if not individual_signals:
                continue

            # Average score of all signals at this timeframe (-1 to 1)
            timeframe_avg_score = sum(
                s.strength
                * (
                    1
                    if s.direction == SignalDirection.BULLISH
                    else -1
                    if s.direction == SignalDirection.BEARISH
                    else 0
                )
                for s in individual_signals
            ) / len(individual_signals)

            # Weight by event duration AND by timeframe reliability
            event_duration_weight = timeframe_contributions.get(timeframe, 0)
            timeframe_reliability_weight = timeframe_signal_weights.get(timeframe, 1.0)

            combined_weight = event_duration_weight * timeframe_reliability_weight

            # Add to running total
            total_score += timeframe_avg_score * combined_weight
            total_weight += combined_weight
            contributing_signals += len(individual_signals)

            # Store for breakdown
            weight_breakdown[timeframe] = {
                "event_weight": event_duration_weight,
                "reliability_weight": timeframe_reliability_weight,
                "combined_weight": combined_weight,
                "signal_count": len(individual_signals),
                "avg_score": timeframe_avg_score,
            }

        # Normalize composite score
        composite_score = total_score / total_weight if total_weight > 0 else 0.0

        # Convert to direction
        if abs(composite_score) < 0.1:
            direction = SignalDirection.NEUTRAL
            confidence = 0.5
        elif composite_score > 0:
            direction = SignalDirection.BULLISH
            confidence = min(abs(composite_score) * 0.8 + 0.2, 0.9)
        else:
            direction = SignalDirection.BEARISH
            confidence = min(abs(composite_score) * 0.8 + 0.2, 0.9)

        # Build reasoning
        contributing_tfs = [
            tf for tf, weight in timeframe_contributions.items() if weight > 0
        ]

        reasoning = f"Timeframe-weighted composite ({total_weight:.1f}): " + " + ".join(
            [
                f"{tf}({weight_breakdown[tf]['combined_weight']:.2f})"
                for tf in contributing_tfs
                if tf in weight_breakdown
            ]
        )

        return {
            "composite_score": composite_score,
            "direction": direction,
            "confidence": confidence,
            "contributing_timeframes": contributing_tfs,
            "weight_breakdown": weight_breakdown,
            "total_signals": contributing_signals,
            "reasoning": reasoning,
        }

    def get_recommended_timeframe(self, hours_until_resolution: float) -> str:
        """
        Get the most appropriate timeframe for an event duration.

        Args:
            hours_until_resolution: Hours until event resolves

        Returns:
            Primary recommended timeframe
        """
        if hours_until_resolution <= 0.5:  # 30 minutes or less (15-min markets)
            return "15m"  # Ultra-short: exclusively 15m
        elif hours_until_resolution <= 6:
            return "15m"
        elif hours_until_resolution <= 24:
            return "30m"
        elif hours_until_resolution <= 168:  # 1 week
            return "1h"
        else:
            return "4h"

    def get_signal_summary(
        self,
        timeframe_signals: Dict[str, TimeframeSignals],
        hours_until_resolution: float,
    ) -> str:
        """
        Get human-readable summary of multi-timeframe signals.

        Args:
            timeframe_signals: Signals from collect_all_signals()
            hours_until_resolution: Event duration for weighting context

        Returns:
            Formatted string summary
        """
        weighted = self.get_weighted_composite_score(
            timeframe_signals, hours_until_resolution
        )

        summary = "\n" + "=" * 80 + "\n"
        summary += "[TARGET] MULTI-TIMEFRAME SIGNAL SUMMARY\n"
        summary += "=" * 80 + "\n"

        summary += f"Event Duration: {hours_until_resolution:.1f} hours\n"
        summary += f"Recommended Primary TF: {self.get_recommended_timeframe(hours_until_resolution)}\n"
        summary += "\n"

        # Show composite score
        score = weighted["composite_score"]
        direction_emoji = (
            "[BULL]" if score > 0 else "[BEAR]" if score < 0 else "[NEUTRAL]"
        )
        summary += f"{direction_emoji} Composite Score: {score:+.2f}\n"
        summary += f"   Confidence: {weighted['confidence']:.1%}\n"
        summary += f"   Signals: {weighted['total_signals']}\n"
        summary += f"   Reasoning: {weighted['reasoning']}\n"

        # Show weight breakdown
        summary += "\n[CHART] Timeframe Weight Breakdown:\n"
        summary += "-" * 80 + "\n"

        for tf, breakdown in weighted["weight_breakdown"].items():
            summary += f"{tf:8} "
            summary += f"| Event: {breakdown['event_weight']:.1%} "
            summary += f"| Reliability: {breakdown['reliability_weight']:.1f}x "
            summary += f"| Combined: {breakdown['combined_weight']:.2f} "
            summary += f"| Signals: {breakdown['signal_count']} "
            summary += f"| Avg: {breakdown['avg_score']:+.2f}"
            summary += "\n"

        # Show individual timeframe details
        summary += "\n[CHART_UP] Individual Timeframe Analysis:\n"
        summary += "=" * 80 + "\n"

        for timeframe, signals in timeframe_signals.items():
            summary += signals.get_signal_summary()

        summary += "=" * 80 + "\n"

        return summary
