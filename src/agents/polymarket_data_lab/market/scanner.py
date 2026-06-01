"""
Crypto Market Scanner

Scans Polymarket for BTC/ETH prediction markets.
Filters, ranks, and returns tradeable opportunities.

Built with love by TradeHive
"""

import sys
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from termcolor import cprint

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.config import CryptoPolymarketConfig
from src.agents.crypto_polymarket.models import CryptoMarket, AggregatedSignal
from src.agents.crypto_polymarket.utils.api_clients import PolymarketAPIClient


class CryptoMarketScanner:
    """
    Scans Polymarket for BTC/ETH prediction markets.

    Filtering criteria:
    - Contains BTC, Bitcoin, ETH, or Ethereum keywords
    - Active and tradeable
    - Sufficient liquidity (configurable minimum)
    - Not expired

    Returns ranked list of markets based on alignment with signals.
    """

    # Keywords to identify crypto markets
    BTC_KEYWORDS = ["btc", "bitcoin", "₿"]
    ETH_KEYWORDS = ["eth", "ethereum", "ether"]

    # Expanded search queries for better market discovery
    # Includes short-duration market queries for 15-min trading
    SEARCH_QUERIES = [
        # Standard queries
        ("bitcoin", "BTC"),
        ("btc", "BTC"),
        ("btc price", "BTC"),
        ("bitcoin price", "BTC"),
        ("ethereum", "ETH"),
        ("eth", "ETH"),
        ("eth price", "ETH"),
        ("ethereum price", "ETH"),
        ("crypto", "BOTH"),
        ("cryptocurrency", "BOTH"),
        # Short-duration market queries (15-min / hourly)
        ("bitcoin 15 minute", "BTC"),
        ("btc 15 minute", "BTC"),
        ("btc hourly", "BTC"),
        ("bitcoin hourly", "BTC"),
        ("bitcoin next hour", "BTC"),
        ("btc up down", "BTC"),
        ("bitcoin up", "BTC"),
        ("bitcoin down", "BTC"),
        ("ethereum 15 minute", "ETH"),
        ("eth 15 minute", "ETH"),
        ("eth hourly", "ETH"),
        ("ethereum hourly", "ETH"),
        ("eth up down", "ETH"),
    ]

    # Price target patterns (multiple patterns for better matching)
    # Pattern 1: "above $100k", "below $100,000", "reach 100K"
    PRICE_PATTERN_KEYWORD = re.compile(
        r"(?:above|below|reach|hit|exceed|over|under|at|to|by)\s*\$?\s*([\d,]+(?:\.\d+)?)\s*([kK])?\b",
        re.IGNORECASE,
    )
    # Pattern 2: Standalone prices "$100K", "$100,000"
    PRICE_PATTERN_DOLLAR = re.compile(
        r"\$([\d,]+(?:\.\d+)?)\s*([kK])?\b", re.IGNORECASE
    )
    # Pattern 3: Number with K suffix "100K", "100k"
    PRICE_PATTERN_K = re.compile(r"\b([\d,]+(?:\.\d+)?)\s*([kK])\b")

    def __init__(self, config: CryptoPolymarketConfig):
        self.config = config
        self.api = PolymarketAPIClient(config)
        self._market_cache: Dict[str, CryptoMarket] = {}
        self._last_scan: Optional[datetime] = None

    def scan_markets(self, force_refresh: bool = False) -> List[CryptoMarket]:
        """
        Scan Polymarket for BTC/ETH prediction markets.

        Args:
            force_refresh: Force a new scan even if cache is fresh

        Returns:
            List of CryptoMarket objects
        """
        # Check cache freshness (5-minute cache)
        if not force_refresh and self._last_scan:
            cache_age = datetime.utcnow() - self._last_scan
            if cache_age < timedelta(minutes=5) and self._market_cache:
                return list(self._market_cache.values())

        # Use dict for deduplication by market_id
        markets_by_id: Dict[str, CryptoMarket] = {}
        btc_count = 0
        eth_count = 0

        # Search all queries
        for query, default_symbol in self.SEARCH_QUERIES:
            try:
                query_markets = self._search_and_filter(query, default_symbol)
                for market in query_markets:
                    if market.market_id not in markets_by_id:
                        markets_by_id[market.market_id] = market
                        if market.symbol == "BTC":
                            btc_count += 1
                        elif market.symbol == "ETH":
                            eth_count += 1
            except Exception as e:
                cprint(f"[WARN] Query '{query}' failed: {e}", "yellow")
                continue

        markets = list(markets_by_id.values())

        # Update cache
        self._market_cache = markets_by_id
        self._last_scan = datetime.utcnow()

        cprint(
            f"[CHART] Found {len(markets)} crypto markets ({btc_count} BTC, {eth_count} ETH)",
            "cyan",
        )

        return markets

    def _search_and_filter(self, query: str, symbol: str) -> List[CryptoMarket]:
        """
        Search for markets matching query and filter for relevance.

        Args:
            query: Search query
            symbol: Symbol (BTC or ETH)

        Returns:
            Filtered list of CryptoMarket objects
        """
        raw_markets = self.api.search_markets(query, limit=100)
        filtered = []

        for market_data in raw_markets:
            market = self._parse_market(market_data, symbol)
            if market and self._is_valid_market(market):
                filtered.append(market)

        return filtered

    def _parse_market(
        self, data: Dict[str, Any], default_symbol: str
    ) -> Optional[CryptoMarket]:
        """
        Parse raw market data into CryptoMarket object.

        Args:
            data: Raw market data from API
            default_symbol: Default symbol if not detected

        Returns:
            CryptoMarket object or None if parsing fails
        """
        try:
            # Extract basic info
            condition_id = data.get("conditionId") or data.get("condition_id", "")
            question = data.get("question", "")
            description = data.get("description", "")

            if not condition_id or not question:
                return None

            # Determine symbol from content
            symbol = self._detect_symbol(question + " " + description, default_symbol)

            # Extract tokens (YES/NO)
            tokens = data.get("tokens", [])
            yes_token_id = ""
            no_token_id = ""

            for token in tokens:
                outcome = token.get("outcome", "").upper()
                if outcome == "YES":
                    yes_token_id = token.get("token_id", "")
                elif outcome == "NO":
                    no_token_id = token.get("token_id", "")

            # Get current prices
            yes_price = 0.0
            no_price = 0.0

            if yes_token_id:
                price = self.api.get_price(yes_token_id, "BUY")
                if price:
                    yes_price = price

            if no_token_id:
                price = self.api.get_price(no_token_id, "BUY")
                if price:
                    no_price = price

            # Parse end date
            end_date_str = data.get("endDate") or data.get("end_date_iso", "")
            end_date = None
            if end_date_str:
                try:
                    end_date = datetime.fromisoformat(
                        end_date_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            # Extract liquidity
            liquidity = float(data.get("liquidity", 0) or data.get("volume", 0) or 0)

            # Extract price target from question
            price_target = self._extract_price_target(question)

            # Determine market type (bullish/bearish prediction)
            market_type = self._determine_market_type(question)

            return CryptoMarket(
                market_id=condition_id,
                question=question,
                symbol=symbol,
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
                yes_price=yes_price,
                no_price=no_price,
                liquidity=liquidity,
                end_date=end_date,
                is_active=data.get("active", True),
                price_target=price_target,
                market_type=market_type,
            )

        except Exception as e:
            cprint(f"Error parsing market: {e}", "red")
            return None

    def _detect_symbol(self, text: str, default: str) -> str:
        """Detect whether market is about BTC or ETH."""
        text_lower = text.lower()

        btc_score = sum(1 for kw in self.BTC_KEYWORDS if kw in text_lower)
        eth_score = sum(1 for kw in self.ETH_KEYWORDS if kw in text_lower)

        if btc_score > eth_score:
            return "BTC"
        elif eth_score > btc_score:
            return "ETH"
        return default

    def _extract_price_target(self, question: str) -> Optional[float]:
        """Extract price target from question text using multiple patterns."""
        # Try patterns in order of specificity
        patterns = [
            self.PRICE_PATTERN_KEYWORD,  # "above $100k"
            self.PRICE_PATTERN_DOLLAR,  # "$100,000"
            self.PRICE_PATTERN_K,  # "100K"
        ]

        for pattern in patterns:
            match = pattern.search(question)
            if match:
                price_str = match.group(1).replace(",", "")
                price = float(price_str)

                # Check for K suffix in group 2
                k_suffix = match.group(2) if len(match.groups()) > 1 else None
                if k_suffix and k_suffix.lower() == "k":
                    price *= 1000

                # Sanity check for crypto prices
                if 1000 <= price <= 500000:  # Reasonable BTC/ETH range
                    return price

        return None

    def _determine_market_type(self, question: str) -> str:
        """
        Determine if market is bullish or bearish prediction.

        Returns:
            'bullish' for upside bets, 'bearish' for downside bets
        """
        question_lower = question.lower()

        bullish_keywords = [
            "above",
            "exceed",
            "reach",
            "hit",
            "over",
            "at least",
            "higher",
        ]
        bearish_keywords = [
            "below",
            "under",
            "fall",
            "drop",
            "crash",
            "lower",
            "less than",
        ]

        bullish_score = sum(1 for kw in bullish_keywords if kw in question_lower)
        bearish_score = sum(1 for kw in bearish_keywords if kw in question_lower)

        if bullish_score > bearish_score:
            return "bullish"
        elif bearish_score > bullish_score:
            return "bearish"
        return "neutral"

    def _is_valid_market(self, market: CryptoMarket) -> bool:
        """
        Check if market meets tradeable criteria.

        Criteria:
        - Has valid token IDs
        - Sufficient liquidity
        - Not expired
        - Is active
        """
        # Must have at least one token
        if not market.yes_token_id and not market.no_token_id:
            return False

        # Must be active
        if not market.is_active:
            return False

        # Check liquidity threshold
        if market.liquidity < self.config.min_market_liquidity:
            return False

        # Check expiration
        if market.end_date:
            if market.end_date < datetime.utcnow():
                return False

        return True

    def rank_markets_by_signal(
        self, markets: List[CryptoMarket], signal: AggregatedSignal
    ) -> List[Tuple[CryptoMarket, float]]:
        """
        Rank markets by alignment with aggregated signal.

        Higher score = better alignment with signal direction.

        Args:
            markets: List of markets to rank
            signal: Aggregated signal from data agents

        Returns:
            List of (market, score) tuples, sorted by score descending
        """
        scored_markets = []

        for market in markets:
            score = self._calculate_alignment_score(market, signal)
            scored_markets.append((market, score))

        # Sort by score descending
        scored_markets.sort(key=lambda x: x[1], reverse=True)

        return scored_markets

    def _calculate_alignment_score(
        self, market: CryptoMarket, signal: AggregatedSignal
    ) -> float:
        """
        Calculate how well a market aligns with the signal.

        Score components:
        - Direction alignment (bullish signal + bullish market)
        - Symbol match
        - Liquidity bonus
        - Price attractiveness (mispriced markets)
        """
        score = 0.0

        # Symbol match bonus
        if market.symbol == signal.symbol or signal.symbol == "BOTH":
            score += 0.2

        # Direction alignment
        from src.agents.crypto_polymarket.config import SignalDirection

        if signal.direction == SignalDirection.BULLISH:
            if market.market_type == "bullish":
                # Bullish signal + bullish market = buy YES
                score += 0.4 * signal.confidence
            else:
                # Bullish signal + bearish market = buy NO
                score += 0.3 * signal.confidence

        elif signal.direction == SignalDirection.BEARISH:
            if market.market_type == "bearish":
                # Bearish signal + bearish market = buy YES
                score += 0.4 * signal.confidence
            else:
                # Bearish signal + bullish market = buy NO
                score += 0.3 * signal.confidence

        # Price attractiveness (mispriced markets)
        # If YES price is low on aligned market, it's more attractive
        if (
            market.market_type == "bullish"
            and signal.direction == SignalDirection.BULLISH
        ):
            if market.yes_price < 0.5:
                score += 0.2 * (0.5 - market.yes_price)

        # Liquidity bonus (normalized)
        liquidity_score = min(1.0, market.liquidity / 100000)
        score += 0.1 * liquidity_score

        return score

    def get_best_market_for_signal(
        self, signal: AggregatedSignal
    ) -> Optional[Tuple[CryptoMarket, str, float]]:
        """
        Find the best market to trade given a signal.

        Returns:
            Tuple of (market, side, score) or None if no suitable market
            side is 'YES' or 'NO'
        """
        markets = self.scan_markets()
        if not markets:
            return None

        ranked = self.rank_markets_by_signal(markets, signal)
        if not ranked:
            return None

        best_market, best_score = ranked[0]

        # Determine which side to trade
        from src.agents.crypto_polymarket.config import SignalDirection

        if signal.direction == SignalDirection.BULLISH:
            if best_market.market_type == "bullish":
                side = "YES"  # Bullish signal + bullish market = buy YES
            else:
                side = "NO"  # Bullish signal + bearish market = buy NO
        elif signal.direction == SignalDirection.BEARISH:
            if best_market.market_type == "bearish":
                side = "YES"  # Bearish signal + bearish market = buy YES
            else:
                side = "NO"  # Bearish signal + bullish market = buy NO
        else:
            # Neutral signal - don't trade
            return None

        return (best_market, side, best_score)

    def get_market_by_id(self, market_id: str) -> Optional[CryptoMarket]:
        """Get a specific market by ID."""
        # Check cache first
        if market_id in self._market_cache:
            return self._market_cache[market_id]

        # Fetch from API
        data = self.api.get_market(market_id)
        if data:
            market = self._parse_market(data, "BTC")
            if market:
                self._market_cache[market_id] = market
                return market

        return None

    def get_market_summary(self, market: CryptoMarket) -> str:
        """Generate a human-readable summary of a market."""
        summary = f"[CHART_UP] {market.symbol} Market: {market.question[:80]}...\n"
        summary += f"   Type: {market.market_type.upper()}\n"
        summary += f"   YES: ${market.yes_price:.2f} | NO: ${market.no_price:.2f}\n"
        summary += f"   Liquidity: ${market.liquidity:,.0f}\n"

        if market.end_date:
            time_left = market.end_date - datetime.utcnow()
            hours_left = time_left.total_seconds() / 3600
            if hours_left < 1:
                summary += f"   Expires: {int(hours_left * 60)} minutes\n"
            elif hours_left < 24:
                summary += f"   Expires: {hours_left:.1f} hours\n"
            else:
                summary += f"   Expires: {time_left.days} days\n"

        if market.price_target:
            summary += f"   Price Target: ${market.price_target:,.0f}\n"

        return summary

    def scan_short_duration_markets(
        self, max_hours: float = 1.0
    ) -> List[CryptoMarket]:
        """
        Scan specifically for short-duration markets (15-min to 1-hour).

        Useful for high-frequency trading on Polymarket.

        Args:
            max_hours: Maximum hours until resolution (default 1 hour)

        Returns:
            List of markets expiring within max_hours
        """
        all_markets = self.scan_markets(force_refresh=True)
        short_markets = []

        for market in all_markets:
            if not market.end_date:
                continue

            hours_left = (market.end_date - datetime.utcnow()).total_seconds() / 3600

            # Filter for short duration markets
            if 0 < hours_left <= max_hours:
                short_markets.append(market)

        cprint(
            f"[CLOCK] Found {len(short_markets)} short-duration markets (<{max_hours}h)",
            "cyan",
        )

        return short_markets

    def get_15min_markets(self) -> List[CryptoMarket]:
        """
        Get markets expiring within 15-30 minutes.

        Primary target for 15-min market trading strategy.

        Returns:
            List of 15-min markets
        """
        return self.scan_short_duration_markets(max_hours=0.5)
