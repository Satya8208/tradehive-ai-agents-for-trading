"""
Base Data Agent

Abstract base class for all market data collection agents.
Built with love by TradeHive
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Optional, Any
import asyncio
from termcolor import cprint

import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.config import CryptoPolymarketConfig, SignalDirection
from src.agents.crypto_polymarket.models import MarketSignal


class BaseDataAgent(ABC):
    """
    Base class for all market data collection agents.

    Each data agent:
    1. Fetches specific market data (liquidations, funding, OI, volume)
    2. Analyzes the data for trading signals
    3. Returns a standardized MarketSignal

    Subclasses must implement:
    - fetch_data(): Fetch raw data from API
    - analyze(): Convert raw data into MarketSignal
    """

    def __init__(self, config: CryptoPolymarketConfig, name: str):
        """
        Initialize the data agent.

        Args:
            config: Agent configuration
            name: Name of this agent (e.g., "liquidation", "funding")
        """
        self.config = config
        self.name = name
        self._last_signal: Optional[MarketSignal] = None
        self._last_fetch_time: Optional[datetime] = None
        self._cache: Dict[str, Any] = {}
        self._cache_ttl_seconds: int = 30

    @abstractmethod
    async def fetch_data(self) -> Dict[str, Any]:
        """
        Fetch raw data from the data source.

        Returns:
            Dict containing raw market data
        """
        pass

    @abstractmethod
    def analyze(self, raw_data: Dict[str, Any]) -> MarketSignal:
        """
        Analyze raw data and produce a trading signal.

        Args:
            raw_data: Raw data from fetch_data()

        Returns:
            MarketSignal with direction, strength, and confidence
        """
        pass

    async def get_signal(self) -> MarketSignal:
        """
        Main entry point: fetch data and return signal.

        This is the method called by the orchestrator.
        Handles caching and error recovery.

        Returns:
            MarketSignal for current market conditions
        """
        try:
            cprint(f"  [{self.name}] Fetching data...", "cyan")

            # Fetch raw data
            raw_data = await self.fetch_data()

            # Analyze and create signal
            signal = self.analyze(raw_data)

            # Cache the result
            self._last_signal = signal
            self._last_fetch_time = datetime.utcnow()

            cprint(
                f"  [{self.name}] Signal: {signal.direction.value} "
                f"(strength: {signal.strength:.2f}, confidence: {signal.confidence:.2f})",
                "green"
                if signal.direction == SignalDirection.BULLISH
                else "red"
                if signal.direction == SignalDirection.BEARISH
                else "yellow",
            )

            return signal

        except Exception as e:
            cprint(f"  [{self.name}] Error: {str(e)}", "red")
            return self._create_error_signal(str(e))

    def _create_error_signal(self, error: str) -> MarketSignal:
        """
        Create a neutral signal when an error occurs.

        Args:
            error: Error message

        Returns:
            Neutral MarketSignal
        """
        return MarketSignal(
            agent_name=self.name,
            timestamp=datetime.utcnow(),
            symbol="BOTH",
            direction=SignalDirection.NEUTRAL,
            strength=0.0,
            confidence=0.0,
            raw_data={"error": error},
            reasoning=f"Error fetching data: {error}",
        )

    def _create_neutral_signal(
        self, symbol: str = "BOTH", reasoning: str = "No significant signal"
    ) -> MarketSignal:
        """
        Create a neutral signal when no clear direction.

        Args:
            symbol: Symbol this signal applies to
            reasoning: Explanation for neutral signal

        Returns:
            Neutral MarketSignal
        """
        return MarketSignal(
            agent_name=self.name,
            timestamp=datetime.utcnow(),
            symbol=symbol,
            direction=SignalDirection.NEUTRAL,
            strength=0.0,
            confidence=0.5,
            raw_data={},
            reasoning=reasoning,
        )

    def get_cached_signal(self) -> Optional[MarketSignal]:
        """
        Get the last cached signal if still valid.

        Returns:
            Last signal if within TTL, None otherwise
        """
        if self._last_signal is None or self._last_fetch_time is None:
            return None

        age = (datetime.utcnow() - self._last_fetch_time).total_seconds()
        if age > self._cache_ttl_seconds:
            return None

        return self._last_signal

    @property
    def last_signal(self) -> Optional[MarketSignal]:
        """Get the last signal (may be stale)"""
        return self._last_signal

    @property
    def last_fetch_time(self) -> Optional[datetime]:
        """Get the timestamp of last successful fetch"""
        return self._last_fetch_time


class SyncDataAgentMixin:
    """
    Mixin for agents that use synchronous API calls.

    Provides helper to run sync code in async context.
    """

    async def run_sync(self, func, *args, **kwargs):
        """
        Run a synchronous function in an async context.

        Args:
            func: Synchronous function to run
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
