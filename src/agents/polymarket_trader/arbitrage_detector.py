"""
Arbitrage Detector for Polymarket CLI Agents

Detects combinatorial and cross-market arbitrage opportunities.
"""

import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
from termcolor import cprint

from .config import PolymarketCLIConfig, get_config
from .models import CLIMarket, ArbitrageOpportunity


class ArbitrageDetector:
    """
    Detects two types of arbitrage on Polymarket:

    1. Combinatorial: Markets with mutually exclusive outcomes that must sum to 1.0
       e.g., P(BTC>110k) must be <= P(BTC>100k) for same date

    2. Complementary: YES_above + YES_below should = 1.0
       e.g., "BTC above $100k" + "BTC below $100k" = 1.0

    3. Cross-Market: Similar questions with different prices
    """

    def __init__(self, config: Optional[PolymarketCLIConfig] = None):
        self.config = config or get_config()

    def _market_qualifies_for_arb(self, market: CLIMarket) -> bool:
        """Strict quality gate so only liquid, active, non-penny markets survive."""
        if not market.is_active:
            return False
        if not market.yes_token_id or not market.no_token_id:
            return False
        if market.liquidity < self.config.min_liquidity_usd:
            return False
        if market.volume_24h < self.config.min_volume_24h_usd:
            return False
        if market.yes_price < self.config.min_arb_token_price:
            return False
        if market.no_price < self.config.min_arb_token_price:
            return False
        if market.yes_price > 1.0 - self.config.min_arb_token_price:
            return False
        if market.no_price > 1.0 - self.config.min_arb_token_price:
            return False
        if market.spread and market.spread > 0.12:
            return False
        if market.end_date and market.time_remaining_hours <= 0:
            return False
        if self.config.max_expiry_hours is not None and market.end_date:
            if market.time_remaining_hours > self.config.max_expiry_hours:
                return False
        return True

    def _pair_is_strict_enough(self, m1: CLIMarket, m2: CLIMarket) -> bool:
        """Require both markets to be clean enough for capital-efficient arb."""
        if not self._market_qualifies_for_arb(m1):
            return False
        if not self._market_qualifies_for_arb(m2):
            return False
        if m1.condition_id == m2.condition_id:
            return False
        if m1.symbol and m2.symbol and m1.symbol != m2.symbol:
            return False
        return True

    def detect_all(self, markets: List[CLIMarket]) -> List[ArbitrageOpportunity]:
        """Run all arbitrage detection methods."""
        opportunities = []
        if self._is_weather_vertical():
            opportunities.extend(self.detect_weather_range_no_arbs(markets))
        else:
            opportunities.extend(self.detect_combinatorial_arbs(markets))
            opportunities.extend(self.detect_complementary_arbs(markets))
            opportunities.extend(self.detect_range_sum_arbs(markets))
            opportunities.extend(self.detect_cross_market_arbs(markets))

        if opportunities:
            cprint(f"Found {len(opportunities)} arbitrage opportunities!", "magenta")
        return opportunities

    def detect_weather_range_no_arbs(self, markets: List[CLIMarket]) -> List[ArbitrageOpportunity]:
        """
        Detect safe weather bucket overpricing.

        Temperature range buckets for the same location/date/metric are mutually
        exclusive when their numeric intervals do not overlap. If the NO basket
        costs less than its worst-case payout, buying every NO token is a
        structural edge and does not require the buckets to be exhaustive.
        """
        opportunities: List[ArbitrageOpportunity] = []
        grouped: Dict[Tuple[str, str, str], List[Tuple[float, float, CLIMarket]]] = defaultdict(list)
        for market in markets:
            if not self._market_qualifies_for_arb(market):
                continue
            parsed = self._parse_weather_temperature_range(market)
            if not parsed:
                continue
            metric, location, target_date, lower, upper = parsed
            grouped[(metric, location, target_date)].append((lower, upper, market))

        for (metric, location, target_date), bucket_rows in grouped.items():
            if len(bucket_rows) < 2:
                continue
            bucket_rows.sort(key=lambda item: (item[0], item[1]))
            if self._weather_ranges_overlap(bucket_rows):
                continue

            bucket_markets, no_cost, worst_case_payout, edge = self._best_weather_no_basket(
                [row[2] for row in bucket_rows]
            )
            if not bucket_markets:
                continue
            if edge < self.config.min_arb_edge_percent:
                continue
            basket_shares = self._weather_no_basket_shares(bucket_markets)
            if basket_shares is None:
                continue
            basket_id = f"weather_no_basket:{location}:{metric}:{target_date}"

            opportunities.append(
                ArbitrageOpportunity(
                    arb_type="weather_range_no_basket",
                    markets=bucket_markets,
                    description=(
                        f"Weather range NO-basket overpricing: {location} {metric} "
                        f"{target_date}, {len(bucket_markets)} exclusive buckets, "
                        f"NO cost={no_cost:.3f}, worst payout={worst_case_payout:.3f}"
                    ),
                    edge_percent=edge,
                    recommended_trades=[
                        {
                            "action": "BUY",
                            "side": "NO",
                            "market_id": market.condition_id,
                            "token_id": market.no_token_id,
                            "price": market.no_price,
                            "size_usd": round(float(market.no_price) * basket_shares, 4),
                            "target_shares": round(basket_shares, 4),
                            "basket_id": basket_id,
                            "basket_leg_count": len(bucket_markets),
                            "reason": "Buy all NO tokens across mutually exclusive weather buckets",
                        }
                        for market in bucket_markets
                    ],
                )
            )
        return opportunities

    def _best_weather_no_basket(
        self,
        markets: List[CLIMarket],
    ) -> Tuple[List[CLIMarket], float, float, float]:
        best_markets: List[CLIMarket] = []
        best_no_cost = 0.0
        best_worst_payout = 0.0
        best_edge = float("-inf")
        no_cost = 0.0
        ordered = sorted(markets, key=lambda market: float(market.yes_price), reverse=True)
        for idx, market in enumerate(ordered, start=1):
            no_cost += float(market.no_price)
            if idx < 2:
                continue
            worst_case_payout = float(idx - 1)
            fee_buffer = idx * self.config.arb_fee_estimate_percent / 100
            edge = (worst_case_payout - no_cost - fee_buffer) * 100
            if edge > best_edge:
                best_markets = ordered[:idx]
                best_no_cost = no_cost
                best_worst_payout = worst_case_payout
                best_edge = edge
        return best_markets, best_no_cost, best_worst_payout, best_edge

    def _weather_no_basket_shares(self, markets: List[CLIMarket]) -> Optional[float]:
        prices = [float(m.no_price) for m in markets if float(m.no_price) > 0]
        if len(prices) != len(markets):
            return None
        min_size = float(getattr(self.config, "min_position_usd", 0.0) or 0.0)
        max_size = float(getattr(self.config, "max_position_usd", 0.0) or 0.0)
        if max_size <= 0:
            return None
        min_shares = max([5.0] + [min_size / price for price in prices])
        max_shares = min(max_size / price for price in prices)
        if min_shares > max_shares:
            return None
        return round(min_shares, 4)

    def detect_combinatorial_arbs(self, markets: List[CLIMarket]) -> List[ArbitrageOpportunity]:
        """
        Check price monotonicity for related markets.

        For bullish markets with same symbol and end date:
        P(BTC > $110k) must be <= P(BTC > $100k)
        If violated, there's an arbitrage.
        """
        opportunities = []
        groups = self._group_by_symbol_and_date(markets)

        for key, group in groups.items():
            fee_buffer = self.config.arb_fee_estimate_percent / 100

            # --- Bullish markets: P(>higher_target) must be <= P(>lower_target) ---
            bullish = [
                m for m in group
                if m.market_type == "bullish" and m.price_target and self._market_qualifies_for_arb(m)
            ]
            if len(bullish) >= 2:
                bullish.sort(key=lambda m: m.price_target)

                for i in range(len(bullish) - 1):
                    lower = bullish[i]   # e.g., BTC > $90k
                    higher = bullish[i + 1]  # e.g., BTC > $95k

                    if not self._pair_is_strict_enough(lower, higher):
                        continue

                    if higher.yes_price > lower.yes_price + fee_buffer:
                        edge = (higher.yes_price - lower.yes_price - fee_buffer) * 100

                        if edge >= self.config.min_arb_edge_percent:
                            opportunities.append(ArbitrageOpportunity(
                                arb_type="combinatorial",
                                markets=[lower, higher],
                                description=(
                                    f"Bullish monotonicity violation: "
                                    f"'{higher.question[:40]}' YES={higher.yes_price:.3f} > "
                                    f"'{lower.question[:40]}' YES={lower.yes_price:.3f}"
                                ),
                                edge_percent=edge,
                                recommended_trades=[
                                    {
                                        "action": "BUY",
                                        "side": "YES",
                                        "market_id": lower.condition_id,
                                        "token_id": lower.yes_token_id,
                                        "price": lower.yes_price,
                                        "reason": f"Lower target ({lower.price_target}) should have higher prob",
                                    },
                                    {
                                        "action": "BUY",
                                        "side": "NO",
                                        "market_id": higher.condition_id,
                                        "token_id": higher.no_token_id,
                                        "price": higher.no_price,
                                        "reason": f"Higher target ({higher.price_target}) should have lower prob",
                                    },
                                ],
                            ))

            # --- Bearish markets: P(dip to $60k) must be <= P(dip to $65k) ---
            # Lower target = harder to reach = lower probability
            bearish = [
                m for m in group
                if m.market_type == "bearish" and m.price_target and self._market_qualifies_for_arb(m)
            ]
            if len(bearish) >= 2:
                bearish.sort(key=lambda m: m.price_target)

                for i in range(len(bearish) - 1):
                    lower_target = bearish[i]   # e.g., BTC dips to $60k (harder)
                    higher_target = bearish[i + 1]  # e.g., BTC dips to $65k (easier)

                    if not self._pair_is_strict_enough(lower_target, higher_target):
                        continue

                    # P(dip to lower) MUST be <= P(dip to higher)
                    if lower_target.yes_price > higher_target.yes_price + fee_buffer:
                        edge = (lower_target.yes_price - higher_target.yes_price - fee_buffer) * 100

                        if edge >= self.config.min_arb_edge_percent:
                            opportunities.append(ArbitrageOpportunity(
                                arb_type="combinatorial",
                                markets=[lower_target, higher_target],
                                description=(
                                    f"Bearish monotonicity violation: "
                                    f"'{lower_target.question[:40]}' YES={lower_target.yes_price:.3f} > "
                                    f"'{higher_target.question[:40]}' YES={higher_target.yes_price:.3f}"
                                ),
                                edge_percent=edge,
                                recommended_trades=[
                                    {
                                        "action": "BUY",
                                        "side": "YES",
                                        "market_id": higher_target.condition_id,
                                        "token_id": higher_target.yes_token_id,
                                        "price": higher_target.yes_price,
                                        "reason": f"Higher target ({higher_target.price_target}) should have higher prob for bearish",
                                    },
                                    {
                                        "action": "BUY",
                                        "side": "NO",
                                        "market_id": lower_target.condition_id,
                                        "token_id": lower_target.no_token_id,
                                        "price": lower_target.no_price,
                                        "reason": f"Lower target ({lower_target.price_target}) should have lower prob for bearish",
                                    },
                                ],
                            ))

        return opportunities

    def detect_complementary_arbs(self, markets: List[CLIMarket]) -> List[ArbitrageOpportunity]:
        """
        Find complementary markets where YES + YES should = 1.0

        Example: "BTC above $100k" + "BTC below $100k" for same date
        If sum < 0.98 or sum > 1.02, there's an edge.
        """
        opportunities = []
        groups = self._group_by_symbol_and_date(markets)

        for key, group in groups.items():
            bullish = {m.price_target: m for m in group
                       if m.market_type == "bullish" and m.price_target and self._market_qualifies_for_arb(m)}
            bearish = {m.price_target: m for m in group
                       if m.market_type == "bearish" and m.price_target and self._market_qualifies_for_arb(m)}

            # Find matching price targets
            for target in set(bullish.keys()) & set(bearish.keys()):
                above = bullish[target]
                below = bearish[target]

                if not self._pair_is_strict_enough(above, below):
                    continue

                price_sum = above.yes_price + below.yes_price
                deviation = abs(price_sum - 1.0)
                fee_buffer = 2.5 * self.config.arb_fee_estimate_percent / 100

                if deviation > fee_buffer and deviation >= 0.02:
                    edge = (deviation - fee_buffer) * 100

                    if edge >= self.config.min_arb_edge_percent:
                        if price_sum < 1.0:
                            # Both underpriced — buy both
                            opportunities.append(ArbitrageOpportunity(
                                arb_type="complementary",
                                markets=[above, below],
                                description=(
                                    f"Complementary underpricing: "
                                    f"above={above.yes_price:.3f} + below={below.yes_price:.3f} "
                                    f"= {price_sum:.3f} < 1.0"
                                ),
                                edge_percent=edge,
                                recommended_trades=[
                                    {
                                        "action": "BUY", "side": "YES",
                                        "market_id": above.condition_id,
                                        "token_id": above.yes_token_id,
                                        "price": above.yes_price,
                                    },
                                    {
                                        "action": "BUY", "side": "YES",
                                        "market_id": below.condition_id,
                                        "token_id": below.yes_token_id,
                                        "price": below.yes_price,
                                    },
                                ],
                            ))
                        else:
                            # Both overpriced — buy both NO tokens
                            opportunities.append(ArbitrageOpportunity(
                                arb_type="complementary",
                                markets=[above, below],
                                description=(
                                    f"Complementary overpricing: "
                                    f"above={above.yes_price:.3f} + below={below.yes_price:.3f} "
                                    f"= {price_sum:.3f} > 1.0"
                                ),
                                edge_percent=edge,
                                recommended_trades=[
                                    {
                                        "action": "BUY", "side": "NO",
                                        "market_id": above.condition_id,
                                        "token_id": above.no_token_id,
                                        "price": above.no_price,
                                    },
                                    {
                                        "action": "BUY", "side": "NO",
                                        "market_id": below.condition_id,
                                        "token_id": below.no_token_id,
                                        "price": below.no_price,
                                    },
                                ],
                            ))

        return opportunities

    def detect_range_sum_arbs(self, markets: List[CLIMarket]) -> List[ArbitrageOpportunity]:
        """
        Detect range-sum arbitrage: "Bitcoin between $X-$Y" markets for the same
        symbol/date should sum to ~1.0 (exhaustive/exclusive outcomes).

        If the sum is significantly != 1.0, there's an arb.
        """
        import re as _re
        opportunities = []
        groups = self._group_by_symbol_and_date(markets)

        for key, group in groups.items():
            # Find "between" markets, skip dead tokens (penny prices)
            range_markets = [
                m for m in group
                if "between" in m.question.lower()
                and m.yes_price >= max(self.config.min_arb_token_price, 0.08)
                and self._market_qualifies_for_arb(m)
            ]

            if len(range_markets) < 3:
                continue

            # Sum YES prices — should be ~1.0 for exhaustive outcomes
            raw_sum = sum(m.yes_price for m in range_markets)

            # Filter out tokens contributing <2% to total sum (noise, not real arb signal)
            if raw_sum > 0:
                range_markets = [
                    m for m in range_markets
                    if m.yes_price / raw_sum >= 0.02
                ]

            if len(range_markets) < 2:
                continue

            price_sum = sum(m.yes_price for m in range_markets)
            deviation = abs(price_sum - 1.0)
            fee_buffer = max(0.03, len(range_markets) * self.config.arb_fee_estimate_percent / 100)

            if deviation > fee_buffer and deviation >= 0.03:
                edge = (deviation - fee_buffer) * 100

                if edge >= self.config.min_arb_edge_percent:
                    # Only trade the top 2 ranges by YES price (most likely to win)
                    # instead of all ranges — prevents diluting profits across N losers
                    sorted_by_price = sorted(range_markets, key=lambda m: m.yes_price, reverse=True)
                    top_ranges = sorted_by_price[:2]

                    if price_sum < 1.0:
                        desc = (f"Range-sum underpricing ({len(range_markets)} ranges, "
                                f"trading top {len(top_ranges)}): sum={price_sum:.3f} < 1.0")
                        trades = [
                            {"action": "BUY", "side": "YES",
                             "market_id": m.condition_id,
                             "token_id": m.yes_token_id,
                             "price": m.yes_price,
                             "reason": f"Buy top range: sum < 1.0"}
                            for m in top_ranges
                        ]
                    else:
                        desc = (f"Range-sum overpricing ({len(range_markets)} ranges, "
                                f"trading top {len(top_ranges)}): sum={price_sum:.3f} > 1.0")
                        trades = [
                            {"action": "BUY", "side": "NO",
                             "market_id": m.condition_id,
                             "token_id": m.no_token_id,
                             "price": m.no_price,
                             "reason": f"Sell top range: sum > 1.0"}
                            for m in top_ranges
                        ]

                    opportunities.append(ArbitrageOpportunity(
                        arb_type="range_sum",
                        markets=range_markets,
                        description=desc,
                        edge_percent=edge,
                        recommended_trades=trades,
                    ))

        return opportunities

    def detect_cross_market_arbs(self, markets: List[CLIMarket]) -> List[ArbitrageOpportunity]:
        """
        Find similar questions with different prices.
        Uses fuzzy matching on question text.
        """
        opportunities = []

        # Compare all pairs (O(n^2) but n is small, ~50 markets)
        for i in range(len(markets)):
            for j in range(i + 1, len(markets)):
                m1, m2 = markets[i], markets[j]

                # Skip same market
                if m1.condition_id == m2.condition_id:
                    continue

                # Skip same-symbol markets with price targets — these are handled
                # by the combinatorial detector, not cross-market
                if (m1.symbol and m1.symbol == m2.symbol and
                        (m1.price_target is not None or m2.price_target is not None)):
                    continue

                # Skip pairs where both have end_dates but they differ by >1 day
                # Different expiry = different market, not arbitrage
                if (m1.end_date and m2.end_date and
                        abs((m1.end_date - m2.end_date).total_seconds()) > 86400):
                    continue

                # Check question similarity
                if not self._pair_is_strict_enough(m1, m2):
                    continue

                similarity = self._fuzzy_match_questions(m1.question, m2.question)
                similarity_floor = max(self.config.arb_fuzzy_match_threshold, 0.82)
                if similarity < similarity_floor:
                    continue

                # Check price divergence
                price_diff = abs(m1.yes_price - m2.yes_price)
                fee_buffer = 2.5 * self.config.arb_fee_estimate_percent / 100

                if price_diff > fee_buffer and price_diff >= 0.03:
                    edge = (price_diff - fee_buffer) * 100

                    if edge >= self.config.min_arb_edge_percent:
                        cheap = m1 if m1.yes_price < m2.yes_price else m2
                        expensive = m2 if m1.yes_price < m2.yes_price else m1

                        opportunities.append(ArbitrageOpportunity(
                            arb_type="cross_market",
                            markets=[cheap, expensive],
                            description=(
                                f"Cross-market divergence ({similarity:.0%} similar): "
                                f"'{cheap.question[:35]}' YES={cheap.yes_price:.3f} vs "
                                f"'{expensive.question[:35]}' YES={expensive.yes_price:.3f}"
                            ),
                            edge_percent=edge,
                            recommended_trades=[
                                {
                                    "action": "BUY", "side": "YES",
                                    "market_id": cheap.condition_id,
                                    "token_id": cheap.yes_token_id,
                                    "price": cheap.yes_price,
                                    "reason": "Cheaper YES on similar market",
                                },
                                {
                                    "action": "BUY", "side": "NO",
                                    "market_id": expensive.condition_id,
                                    "token_id": expensive.no_token_id,
                                    "price": expensive.no_price,
                                    "reason": "Cheaper NO on similar market (expensive YES)",
                                },
                            ],
                        ))

        return opportunities

    def _group_by_symbol_and_date(self, markets: List[CLIMarket]) -> Dict[str, List[CLIMarket]]:
        """Group markets by (symbol, approximate end date)."""
        groups = defaultdict(list)
        for m in markets:
            if m.end_date:
                # Group by date (ignore time)
                date_key = m.end_date.strftime("%Y-%m-%d")
            else:
                date_key = "no_date"
            key = f"{m.symbol}_{date_key}"
            groups[key].append(m)
        return dict(groups)

    def _is_weather_vertical(self) -> bool:
        return str(getattr(self.config, "market_vertical", "crypto") or "crypto").lower() == "weather"

    @staticmethod
    def _parse_weather_temperature_range(
        market: CLIMarket,
    ) -> Optional[Tuple[str, str, str, float, float]]:
        question = str(getattr(market, "question", "") or "")
        lowered = question.lower()
        if "temperature" not in lowered:
            return None

        header = re.search(
            r"\b(highest|maximum|lowest|minimum)\s+temperature\s+in\s+(.+?)\s+be\b",
            question,
            flags=re.IGNORECASE,
        )
        if not header:
            return None
        metric_word = header.group(1).lower()
        metric = "temperature_low" if metric_word in {"lowest", "minimum"} else "temperature_high"
        location = re.sub(r"\s+", " ", header.group(2).strip().lower())
        if not location:
            return None

        if "between" in lowered:
            interval = re.search(
                r"\bbetween\s*(-?\d+(?:\.\d+)?)\s*(?:-|and|to)\s*(-?\d+(?:\.\d+)?)\s*(?:°\s*)?([fc])?\b",
                question,
                flags=re.IGNORECASE,
            )
            if not interval:
                return None
            lower = float(interval.group(1))
            upper = float(interval.group(2))
            unit = (interval.group(3) or "f").lower()
        else:
            if "or below" in lowered or "or higher" in lowered or "or above" in lowered:
                return None
            exact = re.search(
                r"\bbe\s+(-?\d+(?:\.\d+)?)\s*(?:°\s*)?([fc])\b",
                question,
                flags=re.IGNORECASE,
            )
            if not exact:
                return None
            lower = float(exact.group(1))
            upper = lower
            unit = exact.group(2).lower()
        if unit == "c":
            lower = lower * 9.0 / 5.0 + 32.0
            upper = upper * 9.0 / 5.0 + 32.0
        lower, upper = min(lower, upper), max(lower, upper)

        target_date = ArbitrageDetector._parse_question_month_day(question, market.end_date)
        if not target_date:
            return None
        return metric, location, target_date, lower, upper

    @staticmethod
    def _parse_question_month_day(question: str, end_date: Optional[datetime]) -> str:
        match = re.search(
            r"\bon\s+(january|february|march|april|may|june|july|august|september|october|november|december|"
            r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{1,2})(?:,?\s+(\d{4}))?\b",
            question,
            flags=re.IGNORECASE,
        )
        if not match:
            return ""
        month_lookup = {
            "jan": 1,
            "january": 1,
            "feb": 2,
            "february": 2,
            "mar": 3,
            "march": 3,
            "apr": 4,
            "april": 4,
            "may": 5,
            "jun": 6,
            "june": 6,
            "jul": 7,
            "july": 7,
            "aug": 8,
            "august": 8,
            "sep": 9,
            "sept": 9,
            "september": 9,
            "oct": 10,
            "october": 10,
            "nov": 11,
            "november": 11,
            "dec": 12,
            "december": 12,
        }
        month = month_lookup.get(match.group(1).lower())
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else (end_date.year if end_date else 0)
        if not month or not year:
            return ""
        return f"{year:04d}-{month:02d}-{day:02d}"

    @staticmethod
    def _weather_ranges_overlap(bucket_rows: List[Tuple[float, float, CLIMarket]]) -> bool:
        previous_upper: Optional[float] = None
        for lower, upper, _market in bucket_rows:
            if previous_upper is not None and lower <= previous_upper:
                return True
            previous_upper = upper
        return False

    def _fuzzy_match_questions(self, q1: str, q2: str) -> float:
        """
        Word-overlap similarity score, stripping numbers/dates/dollar amounts
        to match on structural similarity only.
        """
        import re

        def strip_noise(q: str) -> set:
            q = q.lower()
            # Strip dollar amounts, numbers, dates, times
            q = re.sub(r'\$[\d,]+\.?\d*[kK]?', '', q)
            q = re.sub(r'\b\d{1,2}:\d{2}\s*(am|pm)\b', '', q, flags=re.IGNORECASE)
            q = re.sub(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}\b', '', q, flags=re.IGNORECASE)
            q = re.sub(r'\b\d+\b', '', q)
            words = set(q.split())
            stop_words = {"will", "the", "a", "an", "in", "by", "to", "of", "?", "or", "on", "-", ""}
            return words - stop_words

        words1 = strip_noise(q1)
        words2 = strip_noise(q2)

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union) if union else 0.0


if __name__ == "__main__":
    from .market_scanner import CLIMarketScanner

    scanner = CLIMarketScanner()
    markets = scanner.scan_markets()

    if markets:
        detector = ArbitrageDetector()
        opps = detector.detect_all(markets)

        if opps:
            print(f"\nFound {len(opps)} arbitrage opportunities:")
            for opp in opps:
                print(f"\n  Type: {opp.arb_type}")
                print(f"  Edge: {opp.edge_percent:.1f}%")
                print(f"  {opp.description}")
                for trade in opp.recommended_trades:
                    print(f"    -> {trade['action']} {trade['side']} @ ${trade['price']:.3f}")
        else:
            print(f"\nNo arbitrage found across {len(markets)} markets")
    else:
        print("No markets to scan")
