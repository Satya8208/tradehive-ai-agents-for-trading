"""
Market Scanner for Polymarket CLI Agents

Discovers, filters, and ranks crypto prediction markets via CLI.
"""

import ast
import json
import math
import time
import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from termcolor import cprint

from .config import PolymarketCLIConfig, get_config
from .cli_wrapper import PolymarketCLI
from .models import CLIMarket


class CLIMarketScanner:
    """
    Discovers crypto prediction markets via Polymarket CLI.
    Filters by liquidity, volume, time remaining, and crypto relevance.
    """

    BTC_KEYWORDS = ["bitcoin", "btc"]
    ETH_KEYWORDS = ["ethereum", "eth", "ether"]
    SOL_KEYWORDS = ["solana", "sol"]
    SYMBOL_KEYWORDS = {
        "BTC": BTC_KEYWORDS,
        "ETH": ETH_KEYWORDS,
        "SOL": SOL_KEYWORDS,
        "XRP": ["xrp"],
        "DOGE": ["doge", "dogecoin"],
        "ADA": ["ada", "cardano"],
        "AVAX": ["avax", "avalanche"],
        "LINK": ["link", "chainlink"],
        "DOT": ["dot", "polkadot"],
    }
    WEATHER_KEYWORDS = [
        "weather",
        "temperature",
        "degrees",
        "fahrenheit",
        "celsius",
        "rain",
        "precipitation",
        "snow",
        "snowfall",
        "wind",
        "wind gust",
        "hurricane",
        "tropical storm",
        "storm",
        "heat",
        "cold",
        "freeze",
        "space weather",
        "geomagnetic",
        "radio blackout",
        "solar radiation",
    ]
    WEATHER_LOCATION_KEYWORDS = [
        "new york",
        "nyc",
        "chicago",
        "miami",
        "austin",
        "los angeles",
        "philadelphia",
        "boston",
        "washington dc",
        "denver",
        "dallas",
        "houston",
        "san francisco",
        "phoenix",
        "atlanta",
        "london",
        "munich",
        "toronto",
    ]

    # Regex patterns for extracting price targets.
    PRICE_PATTERNS = [
        r"(?:above|below|over|under|reach|hit|exceed|surpass)\s*\$?([\d,]+\.?\d*)\s*[kK]?",
        r"\$([\d,]+\.?\d*)\s*[kK]?",
        r"([\d,]+\.?\d*)\s*[kK]\b",
    ]

    def __init__(self, config: Optional[PolymarketCLIConfig] = None,
                 cli: Optional[PolymarketCLI] = None):
        self.config = config or get_config()
        self.cli = cli or PolymarketCLI(self.config)
        self._cache: Dict[str, List[CLIMarket]] = {}
        self._cache_time: float = 0
        self._parse_failures: Counter[str] = Counter()
        self.last_scan_stats: Dict[str, int] = {
            "raw_records": 0,
            "parsed": 0,
            "tradeable": 0,
            "skipped": 0,
        }
        self.last_scan_telemetry: Dict[str, Any] = {
            "cached": False,
            "query_count": 0,
            "raw_records": 0,
            "parsed": 0,
            "filtered": 0,
            "tradeable": 0,
            "no_markets": True,
            "exclusion_reasons": {},
        }

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            parsed = float(str(value).replace(",", ""))
            if parsed != parsed:
                return default
            return parsed
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on", "active", "enabled"}

    @staticmethod
    def _canonical_text(value: str) -> str:
        if not value:
            return ""
        return re.sub(r"\s+", " ", value.strip().lower())

    @staticmethod
    def _canonical_condition_id(condition_id: str) -> str:
        if not condition_id:
            return ""

        parts = [p.strip() for p in str(condition_id).split(":")]
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            return ":".join(sorted(parts))
        return str(condition_id).strip()

    @staticmethod
    def _normalize_token_id(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            if text.lower().startswith("0x"):
                return str(int(text, 16))
        except ValueError:
            pass
        if not re.fullmatch(r"[0-9]+", text):
            return None
        return text

    def _track_skip(self, reason: str) -> None:
        self._parse_failures[reason] += 1
        self.last_scan_stats["skipped"] += 1

    # -------------------------------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------------------------------

    def scan_markets(self, force_refresh: bool = False) -> List[CLIMarket]:
        """
        Full scan: search multiple queries, deduplicate, filter, return.
        Uses cache unless force_refresh or cache expired.
        """
        now = time.time()
        if (
            not force_refresh
            and self._cache.get("markets")
            and self._cache_time + self.config.market_cache_seconds >= now
        ):
            if self._cache.get("markets"):
                cached_markets = self._cache["markets"]
                self.last_scan_stats = {
                    "raw_records": 0,
                    "parsed": 0,
                    "tradeable": len(cached_markets),
                    "skipped": 0,
                }
                self.last_scan_telemetry = {
                    "cached": True,
                    "query_count": 0,
                    "raw_records": 0,
                    "parsed": 0,
                    "filtered": 0,
                    "tradeable": len(cached_markets),
                    "no_markets": len(cached_markets) == 0,
                    "exclusion_reasons": dict(self._parse_failures),
                }
                return self._cache["markets"]

        vertical_label = "weather" if self._is_weather_vertical() else "crypto"
        cprint(f"Scanning for {vertical_label} prediction markets...", "cyan")
        all_markets: Dict[str, CLIMarket] = {}
        self._parse_failures = Counter()
        self.last_scan_stats = {"raw_records": 0, "parsed": 0, "tradeable": 0, "skipped": 0}
        expanded_queries = self._expand_search_queries()
        query_count = 0

        for query, default_symbol in expanded_queries:
            query_count += 1
            raw_results = self.cli.search_markets(query, limit=50)
            if not raw_results:
                self._track_skip("empty_query_result")
                continue

            results = raw_results
            if isinstance(results, dict):
                candidate = results.get("data", results.get("markets", results.get("results")))
                if candidate is None:
                    if self._extract_first_result(results):
                        results = [self._extract_first_result(results)]
                    else:
                        self._track_skip("non_list_results")
                        continue
                else:
                    results = candidate

            if not isinstance(results, list):
                self._track_skip("non_list_results")
                continue

            for raw in results:
                self.last_scan_stats["raw_records"] += 1
                if not isinstance(raw, dict):
                    self._track_skip("non_dict_payload")
                    continue

                market = self._parse_cli_market(raw, default_symbol)
                if not market:
                    continue
                self.last_scan_stats["parsed"] += 1

                key = self._market_dedupe_key(market, raw)
                if not key:
                    self._track_skip("missing_dedupe_key")
                    continue
                if key in all_markets:
                    self._track_skip("duplicate_key")
                    continue

                if self._is_tradeable(market):
                    all_markets[key] = market
                    self.last_scan_stats["tradeable"] += 1

        if self._is_weather_vertical():
            query_count += 1
            for raw in self._weather_tag_event_markets():
                self.last_scan_stats["raw_records"] += 1
                market = self._parse_cli_market(raw, "WEATHER")
                if not market:
                    continue
                self.last_scan_stats["parsed"] += 1
                key = self._market_dedupe_key(market, raw)
                if not key:
                    self._track_skip("missing_dedupe_key")
                    continue
                if key in all_markets:
                    self._track_skip("duplicate_key")
                    continue
                if self._is_tradeable(market):
                    all_markets[key] = market
                    self.last_scan_stats["tradeable"] += 1

        markets = list(all_markets.values())
        filtered = self.last_scan_stats["raw_records"] - self.last_scan_stats["tradeable"]
        self.last_scan_stats["skipped"] = max(self.last_scan_stats["skipped"], filtered)
        self.last_scan_telemetry = {
            "cached": False,
            "query_count": query_count,
            "raw_records": self.last_scan_stats["raw_records"],
            "parsed": self.last_scan_stats["parsed"],
            "filtered": filtered,
            "tradeable": self.last_scan_stats["tradeable"],
            "no_markets": len(markets) == 0,
            "exclusion_reasons": dict(self._parse_failures),
        }
        cprint(f"Found {len(markets)} tradeable {vertical_label} markets", "green")
        if self._parse_failures:
            fail_summary = ", ".join(
                f"{k}:{v}" for k, v in sorted(self._parse_failures.items())
            )
            cprint(f"  Parse/filter skips: {fail_summary}", "yellow")
        if not markets:
            cprint(
                "  No tradeable markets after scan. "
                f"queries={query_count} raw={self.last_scan_stats['raw_records']} "
                f"parsed={self.last_scan_stats['parsed']} filtered={filtered}",
                "yellow",
            )

        self._cache["markets"] = markets
        self._cache_time = now
        return markets

    def _expand_search_queries(self) -> List[Tuple[str, str]]:
        """
        Expand configured queries with recall-oriented variants.

        This keeps the config-driven symbol order intact while adding a few
        broader question shapes that help recover markets missed by the base
        search terms.
        """
        seen = set()
        expanded: List[Tuple[str, str]] = []

        for query, default_symbol in self.config.crypto_search_queries:
            variants = self._query_variants(query, default_symbol)
            for variant_query, variant_symbol in variants:
                normalized = self._canonical_text(variant_query)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                expanded.append((variant_query, variant_symbol))
                if self._is_weather_vertical() and len(expanded) >= int(getattr(self.config, "max_weather_search_queries", 12)):
                    return expanded

        return expanded

    def _query_variants(self, query: str, default_symbol: str) -> List[Tuple[str, str]]:
        variants = [(query, default_symbol)]
        normalized = self._canonical_text(query)
        symbol = self._canonical_symbol(default_symbol)

        if self._is_weather_vertical():
            return variants

        if symbol != "CRYPTO" and normalized:
            extra_queries = [
                f"{query} reach",
                f"{query} hit",
                f"{query} exceed",
                f"will {query}",
            ]
            for variant in extra_queries:
                variants.append((variant.strip(), symbol))

        return variants

    def _weather_tag_event_markets(self) -> List[Dict[str, Any]]:
        if not hasattr(self.cli, "_gamma_request"):
            return []
        raw_markets: List[Dict[str, Any]] = []
        offset = 0
        max_events = int(getattr(self.config, "max_weather_tag_events", 500) or 500)
        while offset < max_events:
            try:
                events = self.cli._gamma_request(
                    "/events",
                    params={
                        "closed": "false",
                        "tag_slug": "weather",
                        "limit": min(100, max_events - offset),
                        "offset": offset,
                        "order": "endDate",
                        "ascending": "true",
                    },
                )
            except Exception as exc:
                self._track_skip(f"weather_tag_scan_error:{exc.__class__.__name__}")
                break
            if not isinstance(events, list) or not events:
                break
            for event in events:
                if not isinstance(event, dict):
                    continue
                for market in event.get("markets", []) or []:
                    if not isinstance(market, dict):
                        continue
                    if hasattr(self.cli, "_gamma_event_market_payload"):
                        raw_markets.append(self.cli._gamma_event_market_payload(event, market))
                    else:
                        payload = dict(market)
                        payload.setdefault("events", [event])
                        raw_markets.append(payload)
            offset += len(events)
            if len(events) < 100:
                break
            time.sleep(0.1)
        return raw_markets

    @staticmethod
    def _extract_first_result(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return None

        for key in ("result", "market", "item", "payload"):
            value = payload.get(key)
            if isinstance(value, dict):
                return value
            if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
                return value[0]
        return None

    def _parse_cli_market(self, data: Dict, default_symbol: str) -> Optional[CLIMarket]:
        """
        Parse raw CLI JSON into CLIMarket dataclass.
        Malformed payloads are skipped with counters and reasons.
        """
        try:
            question = str(data.get("question", "")).strip()
            if not question:
                self._track_skip("missing_question")
                return None

            metadata_blob = self._market_metadata_blob(data)
            if not self._is_target_market(question, data):
                reason = "non_weather_question" if self._is_weather_vertical() else "non_crypto_question"
                self._track_skip(reason)
                return None

            # Token IDs
            clob_token_ids = self._extract_token_ids(data)
            if len(clob_token_ids) < 2:
                self._track_skip("missing_tokens")
                return None

            # Prices
            outcome_prices = data.get("outcomePrices", [0, 0])
            if isinstance(outcome_prices, str):
                try:
                    outcome_prices = ast.literal_eval(outcome_prices)
                except (TypeError, ValueError, SyntaxError):
                    try:
                        parsed_json = json.loads(outcome_prices)
                        if isinstance(parsed_json, (list, tuple)):
                            outcome_prices = parsed_json
                        else:
                            self._track_skip("invalid_prices")
                            return None
                    except (TypeError, ValueError, SyntaxError):
                        outcome_prices = [0, 0]
            try:
                if not isinstance(outcome_prices, (list, tuple)):
                    self._track_skip("invalid_prices")
                    return None
                yes_price = self._safe_float(outcome_prices[0], 0.0)
                no_price = self._safe_float(outcome_prices[1], 0.0) if len(outcome_prices) > 1 else 0.0
            except (TypeError, ValueError, IndexError):
                self._track_skip("invalid_prices")
                return None

            if not (0.0 <= yes_price <= 1.0) or not (0.0 <= no_price <= 1.0):
                self._track_skip("price_out_of_range")
                return None

            # End date
            end_date_raw = (
                data.get("endDate")
                if data.get("endDate") is not None
                else data.get("endDateTs")
                if data.get("endDateTs") is not None
                else data.get("end_date")
            )
            end_date = self._parse_datetime(end_date_raw)
            if end_date is None and end_date_raw is not None:
                self._track_skip("invalid_end_date")
                return None

            # Liquidity / volume / spread
            liquidity = self._safe_float(
                data.get("liquidity", 0)
                or data.get("liquidityUsd", 0)
                or data.get("liquidityNum", 0)
            )
            volume_24h = self._safe_float(
                data.get("volume24hr", data.get("volume_24h", data.get("volumeNum", data.get("volume", 0))))
            )
            spread = self._safe_float(data.get("spread", 0))

            # Detection
            symbol = self._detect_market_symbol(metadata_blob)
            if not symbol:
                default_symbol_canonical = self._canonical_symbol(default_symbol)
                if self._is_weather_vertical():
                    symbol = "WEATHER"
                else:
                    symbol = default_symbol_canonical if default_symbol_canonical == "CRYPTO" else "CRYPTO"
            market_type = self._determine_market_type(question)
            price_target = self._extract_price_target(question)
            duration_minutes = self._parse_duration_minutes(question) if market_type == "binary_updown" else None

            token_id_pair = sorted(clob_token_ids[:2])

            condition_id = str(
                data.get("conditionId")
                or data.get("condition_id")
                or f"{token_id_pair[0]}:{token_id_pair[1]}"
            ).strip()

            if not condition_id:
                self._track_skip("missing_condition_id")
                return None

            is_active = self._safe_bool(data.get("active", True), True) and self._safe_bool(
                data.get("acceptingOrders", True), True
            )

            return CLIMarket(
                condition_id=condition_id,
                question=question,
                symbol=symbol,
                yes_token_id=clob_token_ids[0],
                no_token_id=clob_token_ids[1],
                yes_price=yes_price,
                no_price=no_price,
                liquidity=liquidity,
                volume_24h=volume_24h,
                end_date=end_date,
                is_active=is_active,
                market_type=market_type,
                price_target=price_target,
                duration_minutes=duration_minutes,
                event_slug=str(data.get("slug", "")),
                spread=spread,
                slug=str(data.get("slug", "")),
                description=str(data.get("description", ""))[:200],
            )
        except Exception as e:
            self._track_skip("parse_exception")
            cprint(f"Parse error: {e}", "red")
            return None

    def _extract_token_ids(self, data: Dict) -> List[str]:
        """
        Extract token IDs from CLI payload variants.
        """
        clob_token_ids = data.get("clobTokenIds", data.get("clob_token_ids", []))
        if isinstance(clob_token_ids, str):
            try:
                parsed = ast.literal_eval(clob_token_ids)
                clob_token_ids = parsed
            except (ValueError, SyntaxError):
                clob_token_ids = []

        if isinstance(clob_token_ids, dict):
            clob_token_ids = clob_token_ids.get("tokenIds", [])

        if isinstance(clob_token_ids, list):
            values = clob_token_ids
        else:
            values = []

        if not values:
            # Some CLI payloads include a tokens list.
            token_items = data.get("tokens", [])
            if isinstance(token_items, list):
                for token in token_items:
                    if isinstance(token, dict):
                        token_id = token.get("token_id") or token.get("tokenId") or token.get("id")
                        if token_id:
                            values.append(str(token_id))

        normalized = []
        seen = set()
        for token_id in values[:6]:
            norm = self._normalize_token_id(token_id)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            normalized.append(norm)
        return normalized

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        """
        Parse datetime while tolerating multiple input forms.
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            try:
                seconds = float(value)
                if not math.isfinite(seconds):
                    return None
                if seconds > 1e12:
                    seconds = seconds / 1000.0
                return datetime.fromtimestamp(seconds)
            except (TypeError, ValueError, OverflowError):
                return None
        if not isinstance(value, str):
            return None

        text = value.strip()
        if not text:
            return None

        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            return datetime.fromisoformat(text).replace(tzinfo=None)
        except ValueError:
            if re.fullmatch(r"\d+(\.\d+)?", text):
                try:
                    seconds = float(text)
                    if math.isfinite(seconds):
                        if seconds > 1e12:
                            seconds = seconds / 1000.0
                        return datetime.fromtimestamp(seconds)
                except (TypeError, ValueError, OverflowError):
                    pass
            # Fallback for non-ISO payloads.
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(text, fmt)
                except ValueError:
                    continue
        return None

    @staticmethod
    def _canonical_symbol(symbol: str) -> str:
        return (symbol or "OTHER").strip().upper()

    @staticmethod
    def _append_tag_parts(parts: List[str], tags: Any) -> None:
        if not isinstance(tags, list):
            return
        for tag in tags:
            if isinstance(tag, dict):
                for key in ("slug", "label", "name"):
                    value = tag.get(key)
                    if value:
                        parts.append(str(value))
            elif tag:
                parts.append(str(tag))

    def _market_metadata_parts(self, data: Optional[Dict[str, Any]]) -> List[str]:
        if not isinstance(data, dict):
            return []

        parts: List[str] = []
        for key in (
            "question",
            "description",
            "slug",
            "category",
            "groupItemTitle",
            "eventTitle",
            "eventSlug",
            "eventDescription",
            "eventCategory",
        ):
            value = data.get(key)
            if value:
                parts.append(str(value))

        self._append_tag_parts(parts, data.get("tags"))
        self._append_tag_parts(parts, data.get("eventTags"))

        events = data.get("events")
        if isinstance(events, list):
            for event in events[:4]:
                if not isinstance(event, dict):
                    continue
                for key in ("title", "description", "slug", "category"):
                    value = event.get(key)
                    if value:
                        parts.append(str(value))
                self._append_tag_parts(parts, event.get("tags"))

        return parts

    def _market_metadata_blob(self, data: Optional[Dict[str, Any]]) -> str:
        return " ".join(self._market_metadata_parts(data))

    @staticmethod
    def _contains_keyword(text: str, keyword: str) -> bool:
        normalized = str(keyword or "").strip().lower()
        if not normalized:
            return False
        if " " in normalized or "/" in normalized or "-" in normalized:
            return normalized in text
        return re.search(rf"\b{re.escape(normalized)}\b", text) is not None

    def _has_crypto_tag(self, data: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(data, dict):
            return False
        tag_markers = {
            "crypto",
            "bitcoin",
            "ethereum",
            "solana",
            "stablecoin",
            "defi",
            "airdrop",
        }
        metadata_parts: List[str] = []
        self._append_tag_parts(metadata_parts, data.get("tags"))
        self._append_tag_parts(metadata_parts, data.get("eventTags"))
        events = data.get("events")
        if isinstance(events, list):
            for event in events[:4]:
                if isinstance(event, dict):
                    self._append_tag_parts(metadata_parts, event.get("tags"))
        tag_text = " ".join(metadata_parts).lower()
        return any(self._contains_keyword(tag_text, marker) for marker in tag_markers)

    def _has_weather_tag(self, data: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(data, dict):
            return False
        tag_markers = {
            "weather",
            "climate",
            "science",
            "space weather",
            "hurricane",
            "temperature",
        }
        metadata_parts: List[str] = []
        self._append_tag_parts(metadata_parts, data.get("tags"))
        self._append_tag_parts(metadata_parts, data.get("eventTags"))
        events = data.get("events")
        if isinstance(events, list):
            for event in events[:4]:
                if isinstance(event, dict):
                    self._append_tag_parts(metadata_parts, event.get("tags"))
        tag_text = " ".join(metadata_parts).lower()
        return any(self._contains_keyword(tag_text, marker) for marker in tag_markers)

    def _is_crypto_market(self, question: str, data: Optional[Dict[str, Any]] = None) -> bool:
        metadata = self._market_metadata_blob(data)
        search_text = " ".join(part for part in [question, metadata] if part).lower()

        if not search_text:
            return False
        if self._has_crypto_tag(data):
            return True
        if self._detect_symbol(search_text):
            return True

        for keyword in self.config.crypto_keywords:
            if self._contains_keyword(search_text, keyword):
                return True

        extra_keywords = (
            "airdrop",
            "launch a token",
            "token launch",
            "market cap",
            "fdv",
            "stablecoin",
            "btc/usdt",
            "eth/usdt",
        )
        return any(self._contains_keyword(search_text, keyword) for keyword in extra_keywords)

    def _is_weather_market(self, question: str, data: Optional[Dict[str, Any]] = None) -> bool:
        metadata = self._market_metadata_blob(data)
        search_text = " ".join(part for part in [question, metadata] if part).lower()

        if not search_text:
            return False
        if self._has_weather_tag(data):
            return True

        if any(self._contains_keyword(search_text, keyword) for keyword in self.WEATHER_KEYWORDS):
            return True

        return any(
            self._contains_keyword(search_text, location)
            for location in self.WEATHER_LOCATION_KEYWORDS
        )

    def _is_weather_vertical(self) -> bool:
        return str(getattr(self.config, "market_vertical", "crypto") or "crypto").lower() == "weather"

    def _is_target_market(self, question: str, data: Optional[Dict[str, Any]] = None) -> bool:
        if self._is_weather_vertical():
            return self._is_weather_market(question, data)
        return self._is_crypto_market(question, data)

    def _is_tradeable(self, market: CLIMarket) -> bool:
        """
        Filter: active, sufficient liquidity/volume, not expired, not stale.
        """
        allowed_symbols = {
            str(symbol).strip().upper()
            for symbol in getattr(self.config, "search_symbols", [])
            if str(symbol).strip()
        }
        if (
            getattr(self.config, "enforce_search_symbol_filter", True)
            and allowed_symbols
            and str(getattr(market, "symbol", "")).strip().upper() not in allowed_symbols
        ):
            self._track_skip("symbol_filtered")
            return False
        if not market.is_active:
            self._track_skip("inactive_market")
            return False
        if not market.yes_token_id or not market.no_token_id:
            self._track_skip("missing_token_ids")
            return False

        min_liq = min(self.config.min_liquidity_usd, 1000.0) if market.market_type == "binary_updown" else self.config.min_liquidity_usd
        if market.liquidity < min_liq:
            self._track_skip("low_liquidity")
            return False
        if market.volume_24h < self.config.min_volume_24h_usd:
            self._track_skip("low_volume_24h")
            return False
        if market.end_date and market.time_remaining_hours <= 0:
            self._track_skip("expired_market")
            return False

        if self.config.max_expiry_hours is not None and market.end_date:
            if market.time_remaining_hours > self.config.max_expiry_hours:
                self._track_skip("expiry_too_far")
                return False
        if self.config.min_expiry_hours is not None and market.end_date:
            if market.time_remaining_hours < self.config.min_expiry_hours:
                self._track_skip("expiry_too_soon")
                return False
        if self.config.min_expiry_minutes > 0 and market.end_date:
            if market.time_remaining_hours < (self.config.min_expiry_minutes / 60.0):
                self._track_skip("expiry_too_short")
                return False

        return True

    def _detect_symbol(self, text: str) -> Optional[str]:
        t = text.lower()
        for symbol, keywords in self.SYMBOL_KEYWORDS.items():
            if any(re.search(rf"\b{re.escape(kw)}\b", t) for kw in keywords):
                return symbol
        return None

    def _detect_market_symbol(self, text: str) -> Optional[str]:
        if self._is_weather_vertical():
            lowered = str(text or "").lower()
            if self._is_weather_market(lowered, None):
                return "WEATHER"
            return None
        return self._detect_symbol(text)

    def _determine_market_type(self, question: str) -> str:
        """
        Determine if market is bullish/bearish/neutral/binary_updown.
        """
        q = question.lower()

        if "up or down" in q:
            return "binary_updown"

        bullish = ["above", "over", "exceed", "surpass", "reach", "hit", "higher"]
        bearish = ["below", "under", "fall", "drop", "lower", "crash", "dip"]

        if any(w in q for w in bullish):
            return "bullish"
        if any(w in q for w in bearish):
            return "bearish"
        return "neutral"

    def _parse_duration_minutes(self, question: str) -> Optional[int]:
        """
        Parse duration from short-term Up/Down market questions.
        """
        q = question.strip()

        time_range = re.search(
            r"(\d{1,2}):(\d{2})\s*(AM|PM)\s*-\s*(\d{1,2}):(\d{2})\s*(AM|PM)",
            q,
            re.IGNORECASE,
        )
        if time_range:
            h1, m1, p1 = int(time_range.group(1)), int(time_range.group(2)), time_range.group(3).upper()
            h2, m2, p2 = int(time_range.group(4)), int(time_range.group(5)), time_range.group(6).upper()

            if p1 == "PM" and h1 != 12:
                h1 += 12
            if p1 == "AM" and h1 == 12:
                h1 = 0
            if p2 == "PM" and h2 != 12:
                h2 += 12
            if p2 == "AM" and h2 == 12:
                h2 = 0

            total1 = h1 * 60 + m1
            total2 = h2 * 60 + m2
            if total2 <= total1:
                total2 += 24 * 60
            return total2 - total1

        single_time = re.search(r"(\d{1,2})\s*(AM|PM)\s*ET", q, re.IGNORECASE)
        if single_time and "up or down" in q.lower():
            return 60

        return None

    def _extract_price_target(self, question: str) -> Optional[float]:
        """
        Extract price target from question using regex.
        """
        for pattern in self.PRICE_PATTERNS:
            matches = re.findall(pattern, question, re.IGNORECASE)
            if not matches:
                continue
            try:
                raw = matches[0]
                value_str = str(raw).replace(",", "")
                value = float(value_str)
            except ValueError:
                continue

            full_match = re.search(pattern, question, re.IGNORECASE)
            if full_match:
                next_char = question[full_match.end() : full_match.end() + 1].lower()
                if "k" in next_char and value < 10000:
                    value *= 1000
            if value < 100 and "k" in question.lower():
                value *= 1000
            if value > 0:
                return value
        return None

    def _market_dedupe_key(self, market: CLIMarket, raw: Dict[str, Any]) -> str:
        """
        Canonical dedupe key with conditionId fallback to token pair + slug/question.
        """
        if market.condition_id:
            return f"cond:{self._canonical_condition_id(market.condition_id)}"
        token_pair = sorted(filter(None, [market.yes_token_id, market.no_token_id]))
        if len(token_pair) == 2:
            return f"tokens:{token_pair[0]}:{token_pair[1]}"
        slug = str(raw.get("slug", "")).strip().lower()
        if slug:
            return f"slug:{slug}"
        symbol = self._canonical_symbol(str(getattr(market, "symbol", "")))
        question = self._canonical_text(getattr(market, "question", ""))
        if symbol and question:
            return f"sym:{symbol}:{question}"
        if question:
            return f"q:{question}"
        return f"q:{market.condition_id}"

    def rank_markets(self, markets: List[CLIMarket]) -> List[Tuple[CLIMarket, float]]:
        """
        Score markets by tradability and recall-friendly alpha structure.
        Higher score = more attractive for analysis.
        """
        scored = []
        preferred_symbols = {
            symbol: idx for idx, symbol in enumerate(self.config.search_symbols)
        }
        for market in markets:
            score = 0.0

            if market.liquidity > 0:
                import math
                liq_score = min(1.0, math.log10(max(1.0, market.liquidity)) / 4.5)
                score += 0.32 * liq_score

            if market.volume_24h > 0:
                vol_score = min(1.0, math.log10(max(1.0, market.volume_24h)) / 4.5)
                score += 0.30 * vol_score

            if market.spread >= 0:
                spread_score = max(0.0, 1.0 - min(1.0, market.spread / 0.12))
                score += 0.18 * spread_score

            hours = market.time_remaining_hours
            if market.market_type == "binary_updown" and market.duration_minutes is not None:
                if market.duration_minutes <= 15:
                    score += 0.18
                elif market.duration_minutes <= 60:
                    score += 0.16
                elif market.duration_minutes <= 240:
                    score += 0.12
                else:
                    score += 0.08
            elif 0.08 <= hours <= 12:
                score += 0.18
            elif 12 < hours <= 24:
                score += 0.16
            elif 24 < hours <= 72:
                score += 0.10
            elif hours > 72:
                score += 0.04

            yes_p = market.yes_price
            if 0.15 <= yes_p <= 0.85:
                score += 0.12
            elif 0.05 <= yes_p <= 0.95:
                score += 0.06

            if market.price_target is not None:
                score += 0.08
            if market.market_type in {"bullish", "bearish"}:
                score += 0.04

            symbol_rank = preferred_symbols.get(market.symbol, len(preferred_symbols))
            if preferred_symbols:
                symbol_bonus = max(0.0, 0.10 - 0.02 * symbol_rank)
                score += symbol_bonus

            scored.append((market, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def get_markets_by_symbol(self, markets: List[CLIMarket], symbol: str) -> List[CLIMarket]:
        return [m for m in markets if m.symbol == symbol]

    def get_related_markets(self, markets: List[CLIMarket], symbol: str) -> List[CLIMarket]:
        return [m for m in markets if m.symbol == symbol and m.price_target is not None]


if __name__ == "__main__":
    scanner = CLIMarketScanner()
    markets = scanner.scan_markets()

    if markets:
        ranked = scanner.rank_markets(markets)
        print(f"\nTop {min(10, len(ranked))} markets:")
        print("-" * 80)
        for market, score in ranked[:10]:
            q = market.question[:55]
            print(
                f"  [{market.symbol:5s}] {q:<55s} YES=${market.yes_price:.3f}  "
                f"Liq=${market.liquidity:,.0f}  Score={score:.2f}"
            )
    else:
        print("No markets found")
