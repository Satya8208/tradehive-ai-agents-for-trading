"""
Polymarket CLI Wrapper

Single point of contact with the /usr/local/bin/polymarket binary.
All methods return parsed Python dicts/lists from CLI JSON output.
"""

import json
import math
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from termcolor import cprint

from .config import PolymarketCLIConfig, get_config

BUY = "BUY"
SELL = "SELL"
OrderType = None
_CLOB_IMPORT_ERROR: Optional[str] = None

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import (
        AssetType,
        BalanceAllowanceParams,
        OrderArgs,
        OrderType,
    )
    try:
        from py_clob_client.order_builder.constants import BUY, SELL
    except Exception:
        pass
    HAS_CLOB_CLIENT = True
except Exception as exc:
    HAS_CLOB_CLIENT = False
    _CLOB_IMPORT_ERROR = str(exc)


@dataclass
class CLIExecutionResult:
    success: bool
    payload: Optional[Any] = None
    raw: str = ""
    error: Optional[str] = None
    error_code: Optional[str] = None
    source: str = "cli"


class PolymarketCLI:
    """
    Wrapper around the Polymarket CLI binary.

    All modules should call this instead of shelling out directly.
    """

    def __init__(self, config: Optional[PolymarketCLIConfig] = None):
        self.config = config or get_config()
        self.binary = self.config.cli_binary
        self.timeout = self.config.cli_timeout_seconds
        self._last_call_time = 0.0
        self._call_count = 0
        self._clob_client = None
        self._eoa_address: str = ""
        self._cli_available = False
        self._cli_binary_check_error: Optional[str] = None
        self._rest_session = requests.Session()
        self._gamma_url = str(getattr(self.config, "polymarket_gamma_url", "https://gamma-api.polymarket.com")).rstrip("/")
        self._gamma_catalog_cache: Dict[str, Any] = {
            "markets": [],
            "fetched_at": 0.0,
        }
        self._verify_binary()

        if self.config.use_direct_api:
            self._init_clob_client()

    @staticmethod
    def _is_retryable_error(message: str, returncode: int = 0) -> bool:
        if returncode in {429, 500, 502, 503, 504}:
            return True

        lowered = (message or "").lower()
        return any(
            token in lowered
            for token in (
                "timed out",
                "timeout",
                "rate limit",
                "temporary",
                "econnreset",
                "connection reset",
                "connection closed",
                "temporarily unavailable",
                "service unavailable",
                "socket hang up",
            )
        )

    @property
    def cli_available(self) -> bool:
        return self._cli_available

    def _mark_cli_unavailable(self, reason: str) -> None:
        self._cli_available = False
        self._cli_binary_check_error = str(reason) if reason else "CLI unavailable"

    def _verify_binary(self):
        """Check CLI binary exists and is executable."""
        if not self.binary:
            self._mark_cli_unavailable("CLI binary path is empty")
            cprint("Polymarket CLI path is empty", "yellow")
            return

        try:
            result = subprocess.run(
                [self.binary, "--version"],
                capture_output=True,
                text=True,
                timeout=min(self.timeout, 10),
            )
            if result.returncode == 0:
                self._cli_available = True
                self._cli_binary_check_error = None
                version = (result.stdout or result.stderr or "").strip()
                cprint(f"Polymarket CLI ready: {version}", "green")
            else:
                self._mark_cli_unavailable(
                    result.stderr or result.stdout or "non-zero --version exit"
                )
                self._cli_binary_check_error = self._cli_binary_check_error.strip()
                cprint(f"Polymarket CLI warning: {self._cli_binary_check_error}", "yellow")
        except FileNotFoundError:
            self._mark_cli_unavailable(f"Binary not found at {self.binary}")
            if self.config.use_direct_api:
                cprint(
                    f"Polymarket CLI not found at {self.binary} — direct API mode only",
                    "yellow",
                )
            else:
                cprint(f"Polymarket CLI not found at {self.binary}", "yellow")
        except OSError as exc:
            self._mark_cli_unavailable(f"CLI binary unavailable at {self.binary}: {exc}")
            cprint(f"Polymarket CLI unavailable at {self.binary}: {exc}", "yellow")
        except subprocess.TimeoutExpired:
            self._mark_cli_unavailable("CLI version check timed out")
            cprint("Polymarket CLI version check timed out", "yellow")

    @staticmethod
    def _extract_json(payload_text: str) -> tuple[Optional[Any], Optional[str]]:
        """Extract JSON payload from stdout/stderr that may include wrappers/noise."""
        if not isinstance(payload_text, str):
            return None, "No text payload"

        ansi_re = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
        text = payload_text.strip()
        if not text:
            return None, "Empty payload"

        cleaned = ansi_re.sub("", text)

        try:
            return json.loads(cleaned), None
        except Exception:
            pass

        # Common wrappers: logs with code block JSON.
        match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", cleaned, re.DOTALL | re.IGNORECASE)
        if match:
            try:
                return json.loads(match.group(1)), None
            except Exception:
                pass

        decoder = json.JSONDecoder()
        for index, char in enumerate(cleaned):
            if char not in "[{":
                continue
            try:
                value, consumed = decoder.raw_decode(cleaned[index:])
                if consumed > 0:
                    return value, None
            except Exception:
                continue

        return None, "No JSON payload found"

    @staticmethod
    def _to_bool(raw: Any) -> bool:
        if isinstance(raw, bool):
            return raw
        if raw is None:
            return False
        return str(raw).strip().lower() in {"1", "true", "yes", "on", "enabled"}

    @staticmethod
    def _to_float(raw: Any) -> Optional[float]:
        try:
            parsed = float(raw)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(parsed):
            return None
        return parsed

    def _run_direct_or_cli(
        self,
        direct_fn,
        args: List[str],
        use_json: bool = True,
        allow_without_client: bool = False,
    ) -> CLIExecutionResult:
        """
        Execute via direct API first, then fallback to CLI with identical envelope.
        """
        last_direct_error = None
        if direct_fn and (allow_without_client or self._clob_client):
            try:
                payload = direct_fn()
                if payload is None:
                    raise RuntimeError("direct api returned empty payload")
                return CLIExecutionResult(
                    success=True,
                    payload=payload,
                    raw="",
                    source="direct",
                    error_code="direct_success",
                )
            except Exception as e:
                last_direct_error = f"Direct API call failed: {e}"
                cprint(f"{last_direct_error}, falling back to CLI", "yellow")

        cli_result = self._execute(args, use_json=use_json)
        if cli_result.success:
            cli_result.source = "cli"
            return cli_result

        if last_direct_error:
            return CLIExecutionResult(
                success=False,
                raw=cli_result.raw,
                payload=None,
                error=f"{last_direct_error} | CLI fallback error: {cli_result.error}",
                error_code=cli_result.error_code or "direct_and_cli_failed",
                source="cli",
            )

        return cli_result

    def _execute(self, args: List[str], use_json: bool = True,
                 allow_json_noise: bool = True) -> CLIExecutionResult:
        """
        Core execution method.

        - retry/backoff for transient failures
        - strict result schema for call sites
        - explicit error categorization
        """
        if not self._cli_available and not self.config.use_direct_api:
            return CLIExecutionResult(
                success=False,
                raw="",
                error="CLI binary unavailable",
                error_code="cli_unavailable",
                source="cli",
            )

        if not args:
            return CLIExecutionResult(
                success=False,
                raw="",
                error="empty command",
                error_code="bad_command",
                source="cli",
            )

        retries = max(0, self.config.cli_retry_count)
        max_attempts = retries + 1
        cmd = [self.binary] + args
        if use_json:
            cmd += ["--output", "json"]

        last_error = None
        for attempt in range(max_attempts):
            elapsed_ms = (time.time() - self._last_call_time) * 1000
            required_delay_ms = self.config.cli_rate_limit_ms - elapsed_ms
            if required_delay_ms > 0:
                time.sleep(required_delay_ms / 1000)

            self._last_call_time = time.time()
            self._call_count += 1

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=min(self.timeout, 120),
                )
            except subprocess.TimeoutExpired:
                last_error = "command timeout"
                if attempt < max_attempts - 1:
                    time.sleep(self.config.cli_retry_backoff_seconds * (attempt + 1))
                    continue
                return CLIExecutionResult(
                    success=False,
                    raw="",
                    error=last_error,
                    error_code="timeout",
                    source="cli",
                )
            except FileNotFoundError:
                self._mark_cli_unavailable("binary not found")
                last_error = "binary not found"
                return CLIExecutionResult(
                    success=False,
                    raw="",
                    error=last_error,
                    error_code="cli_unavailable",
                    source="cli",
                )
            except OSError as e:
                self._mark_cli_unavailable(f"binary unavailable: {e}")
                last_error = f"binary unavailable: {e}"
                if attempt < max_attempts - 1:
                    time.sleep(self.config.cli_retry_backoff_seconds * (attempt + 1))
                    continue
                return CLIExecutionResult(
                    success=False,
                    raw="",
                    error=last_error,
                    error_code="cli_unavailable",
                    source="cli",
                )
            except Exception as e:
                last_error = str(e)
                if attempt < max_attempts - 1:
                    time.sleep(self.config.cli_retry_backoff_seconds * (attempt + 1))
                    continue
                return CLIExecutionResult(
                    success=False,
                    raw="",
                    error=last_error,
                    error_code="unexpected",
                    source="cli",
                )

            stdout = result.stdout or ""
            stderr = result.stderr or ""
            raw_payload = f"{stdout}\\n{stderr}" if allow_json_noise else stdout
            stderr_lower = stderr.lower()

            if result.returncode != 0:
                if attempt < max_attempts - 1:
                    if self._is_retryable_error(stderr_lower, result.returncode):
                        time.sleep(self.config.cli_retry_backoff_seconds * (attempt + 1))
                        continue
                return CLIExecutionResult(
                    success=False,
                    raw=raw_payload,
                    error=f"bad return code: {result.returncode}",
                    error_code="bad_command",
                    source="cli",
                )

            if not use_json:
                return CLIExecutionResult(
                    success=True,
                    payload=stdout,
                    raw=raw_payload,
                    source="cli",
                )

            payload, parse_error = self._extract_json(raw_payload)
            if parse_error:
                if attempt < max_attempts - 1 and self._is_retryable_error(
                    raw_payload,
                    0,
                ):
                    time.sleep(self.config.cli_retry_backoff_seconds * (attempt + 1))
                    continue
                if attempt >= max_attempts - 1:
                    cprint(
                        f"CLI JSON parse failed after {max_attempts} attempt(s): {parse_error}",
                        "yellow",
                    )
                return CLIExecutionResult(
                    success=False,
                    raw=raw_payload,
                    error=parse_error,
                    error_code="bad_json",
                    source="cli",
                )

            return CLIExecutionResult(success=True, payload=payload, raw=raw_payload, source="cli")

        return CLIExecutionResult(
            success=False,
            raw="",
            error=last_error or "retry_exhausted",
            error_code="retry_exhausted",
            source="cli",
        )

    def _convert_result(self, result: CLIExecutionResult) -> Optional[Any]:
        if not result.success:
            cprint(f"CLI [{result.source}] {result.error_code}: {result.error}", "red")
            return None
        return result.payload

    def status(self) -> Dict[str, Any]:
        """
        Lightweight health/status command entrypoint.
        """
        return self.get_health_status()

    def _convert_cli_result(self, direct_fn, cli_args: List[str],
                           source_name: str, use_json: bool = True,
                           allow_without_client: bool = False) -> Optional[Any]:
        result = self._run_direct_or_cli(
            direct_fn,
            cli_args,
            use_json=use_json,
            allow_without_client=allow_without_client,
        )
        if not result.success:
            cprint(
                f"{source_name} failed [{result.error_code}]: {result.error}",
                "red",
            )
            return None
        return result.payload

    def _normalize_path(self, value: str) -> str:
        return str(Path(value).expanduser().resolve()) if value else value

    def _gamma_request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        response = self._rest_session.get(
            f"{self._gamma_url}{path}",
            params=params or {},
            timeout=min(max(self.timeout, 10), 30),
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _gamma_order_param(order: str) -> str:
        normalized = str(order or "").strip()
        if not normalized:
            return "volume"
        mapping = {
            "volume_num": "volume",
            "volumenum": "volume",
            "liquidity_num": "liquidity",
            "liquiditynum": "liquidity",
            "created_at": "createdAt",
            "updated_at": "updatedAt",
        }
        return mapping.get(normalized.lower(), normalized)

    @staticmethod
    def _coerce_market_list(payload: Any) -> List[Dict]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("markets", "data", "results"):
                candidate = payload.get(key)
                if isinstance(candidate, list):
                    return [item for item in candidate if isinstance(item, dict)]
        return []

    @staticmethod
    def _gamma_market_key(market: Dict[str, Any]) -> str:
        for key in ("conditionId", "condition_id", "id", "slug", "question"):
            value = market.get(key)
            if value:
                return str(value).strip()
        return ""

    @staticmethod
    def _gamma_merge_market_metadata(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
        if not existing:
            return dict(incoming)

        merged = dict(existing)
        for key, value in incoming.items():
            if value in (None, "", [], {}):
                continue

            current = merged.get(key)
            if current in (None, "", [], {}):
                merged[key] = value
                continue

            if isinstance(current, list) and isinstance(value, list):
                combined = list(current)
                seen = {json.dumps(item, sort_keys=True, default=str) for item in combined}
                for item in value:
                    marker = json.dumps(item, sort_keys=True, default=str)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    combined.append(item)
                merged[key] = combined
        return merged

    @staticmethod
    def _gamma_event_market_payload(event: Dict[str, Any], market: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(market)
        event_tags = event.get("tags") if isinstance(event.get("tags"), list) else []
        event_stub = {
            "title": event.get("title"),
            "slug": event.get("slug"),
            "description": event.get("description"),
            "category": event.get("category"),
            "tags": event_tags,
        }

        payload["eventTitle"] = event.get("title", payload.get("eventTitle", ""))
        payload["eventSlug"] = event.get("slug", payload.get("eventSlug", ""))
        payload["eventDescription"] = event.get("description", payload.get("eventDescription", ""))
        payload["eventCategory"] = event.get("category", payload.get("eventCategory", ""))
        if event_tags:
            payload["eventTags"] = event_tags
            if not payload.get("tags"):
                payload["tags"] = event_tags
        if not payload.get("category") and event.get("category"):
            payload["category"] = event.get("category")

        existing_events = payload.get("events")
        if isinstance(existing_events, list):
            payload["events"] = existing_events + [event_stub]
        else:
            payload["events"] = [event_stub]
        return payload

    @staticmethod
    def _gamma_tag_texts(tags: Any) -> List[str]:
        parts: List[str] = []
        if not isinstance(tags, list):
            return parts
        for tag in tags:
            if isinstance(tag, dict):
                for key in ("slug", "label", "name"):
                    value = tag.get(key)
                    if value:
                        parts.append(str(value))
            elif tag:
                parts.append(str(tag))
        return parts

    def _gamma_market_search_text(self, market: Dict[str, Any]) -> str:
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
            value = market.get(key)
            if value:
                parts.append(str(value))

        parts.extend(self._gamma_tag_texts(market.get("tags")))
        parts.extend(self._gamma_tag_texts(market.get("eventTags")))

        events = market.get("events")
        if isinstance(events, list):
            for event in events[:4]:
                if not isinstance(event, dict):
                    continue
                for key in ("title", "description", "slug", "category"):
                    value = event.get(key)
                    if value:
                        parts.append(str(value))
                parts.extend(self._gamma_tag_texts(event.get("tags")))

        return " ".join(part for part in parts if part)

    def _gamma_prepare_market_index(self, market: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(market, dict):
            return market

        if "_gamma_query_blob" in market:
            return market

        search_text = self._gamma_normalize_text(self._gamma_market_search_text(market))
        market["_gamma_query_text"] = search_text
        market["_gamma_query_blob"] = f" {search_text} " if search_text else " "
        market["_gamma_accepting_orders"] = self._to_bool(market.get("acceptingOrders"))
        market["_gamma_active"] = self._to_bool(market.get("active"))
        market["_gamma_volume"] = (
            self._to_float(market.get("volume24hr"))
            or self._to_float(market.get("volumeNum"))
            or self._to_float(market.get("volume"))
            or 0.0
        )
        market["_gamma_liquidity"] = (
            self._to_float(market.get("liquidity"))
            or self._to_float(market.get("liquidityNum"))
            or self._to_float(market.get("liquidityUsd"))
            or 0.0
        )
        return market

    @staticmethod
    def _gamma_normalize_text(value: Any) -> str:
        return re.sub(r"[^a-z0-9$]+", " ", str(value or "").lower()).strip()

    @staticmethod
    def _gamma_query_tokens(query: str) -> List[str]:
        stop_words = {
            "a",
            "an",
            "and",
            "by",
            "for",
            "in",
            "market",
            "markets",
            "of",
            "or",
            "price",
            "the",
            "to",
            "will",
        }
        return [
            token
            for token in re.findall(r"[a-z0-9$]+", str(query or "").lower())
            if len(token) >= 2 and token not in stop_words
        ]

    @staticmethod
    def _gamma_aliases_for_query(query: str) -> List[str]:
        lowered = str(query or "").lower()
        alias_map = {
            "btc": {"btc", "bitcoin"},
            "bitcoin": {"btc", "bitcoin"},
            "eth": {"eth", "ethereum", "ether"},
            "ethereum": {"eth", "ethereum", "ether"},
            "ether": {"eth", "ethereum", "ether"},
            "sol": {"sol", "solana"},
            "solana": {"sol", "solana"},
            "xrp": {"xrp"},
            "doge": {"doge", "dogecoin"},
            "dogecoin": {"doge", "dogecoin"},
            "ada": {"ada", "cardano"},
            "cardano": {"ada", "cardano"},
            "avax": {"avax", "avalanche"},
            "avalanche": {"avax", "avalanche"},
            "link": {"link", "chainlink"},
            "chainlink": {"link", "chainlink"},
            "dot": {"dot", "polkadot"},
            "polkadot": {"dot", "polkadot"},
            "crypto": {"crypto", "airdrop", "token", "stablecoin", "fdv", "market cap"},
        }
        aliases = set()
        for trigger, values in alias_map.items():
            if re.search(rf"\b{re.escape(trigger)}\b", lowered):
                aliases.update(values)
        if "up or down" in lowered:
            aliases.add("up or down")
        return sorted(aliases)

    def _gamma_market_query_score(self, market: Dict[str, Any], query: str) -> float:
        market = self._gamma_prepare_market_index(market)
        search_text = str(market.get("_gamma_query_text", "") or "")
        if not search_text:
            return 0.0
        search_blob = str(market.get("_gamma_query_blob", " ") or " ")

        query_norm = self._gamma_normalize_text(query)
        tokens = self._gamma_query_tokens(query)
        aliases = self._gamma_aliases_for_query(query)
        score = 0.0

        if query_norm and query_norm in search_text:
            score += 8.0

        matched_tokens = [
            token
            for token in tokens
            if f" {token} " in search_blob
        ]
        score += 2.0 * len(matched_tokens)

        alias_hits = []
        for alias in aliases:
            if alias == "up or down":
                if "up or down" in search_text:
                    alias_hits.append(alias)
                continue
            if f" {alias} " in search_blob:
                alias_hits.append(alias)
        if alias_hits:
            score += 3.0 + 0.5 * len(alias_hits)

        if score <= 0.0:
            return 0.0

        if bool(market.get("_gamma_accepting_orders")):
            score += 2.0
        if bool(market.get("_gamma_active")):
            score += 1.0

        volume = float(market.get("_gamma_volume", 0.0) or 0.0)
        liquidity = float(market.get("_gamma_liquidity", 0.0) or 0.0)
        score += min(3.0, volume / 5000.0)
        score += min(2.0, liquidity / 20000.0)
        return score

    def _gamma_active_market_catalog(self, limit: int = 500) -> List[Dict]:
        cache = self._gamma_catalog_cache
        now = time.time()
        cache_ttl = max(30.0, min(float(self.config.market_cache_seconds), 300.0))
        cached_markets = cache.get("markets") or []
        if cached_markets and (now - float(cache.get("fetched_at", 0.0))) <= cache_ttl:
            return [dict(item) for item in cached_markets]

        catalog: Dict[str, Dict[str, Any]] = {}
        errors: List[str] = []
        market_orders = ("updatedAt", "volume", "liquidity")

        for order in market_orders:
            try:
                payload = self._gamma_request(
                    "/markets",
                    params={
                        "limit": limit,
                        "active": "true",
                        "closed": "false",
                        "order": order,
                    },
                )
            except Exception as exc:
                errors.append(f"markets[{order}]: {exc}")
                continue

            for market in self._coerce_market_list(payload):
                key = self._gamma_market_key(market)
                if not key:
                    continue
                catalog[key] = self._gamma_merge_market_metadata(catalog.get(key, {}), market)

        try:
            payload = self._gamma_request(
                "/events",
                params={"limit": limit, "active": "true", "closed": "false"},
            )
        except Exception as exc:
            errors.append(f"events: {exc}")
        else:
            if isinstance(payload, list):
                for event in payload:
                    if not isinstance(event, dict):
                        continue
                    markets = event.get("markets")
                    if not isinstance(markets, list):
                        continue
                    for market in markets:
                        if not isinstance(market, dict):
                            continue
                        merged_market = self._gamma_event_market_payload(event, market)
                        key = self._gamma_market_key(merged_market)
                        if not key:
                            continue
                        catalog[key] = self._gamma_merge_market_metadata(
                            catalog.get(key, {}),
                            merged_market,
                        )

        markets = [self._gamma_prepare_market_index(market) for market in catalog.values()]
        if not markets:
            if cached_markets:
                return [dict(item) for item in cached_markets]
            if errors:
                raise RuntimeError("; ".join(errors))
            return []

        self._gamma_catalog_cache = {
            "markets": markets,
            "fetched_at": now,
        }
        return [dict(item) for item in markets]

    def _gamma_search_markets(self, query: str, limit: int = 50) -> List[Dict]:
        candidates: Dict[str, Dict[str, Any]] = {}
        query_lower = str(query or "").lower()
        if any(
            token in query_lower
            for token in ("weather", "temperature", "rain", "snow", "wind", "hurricane", "storm")
        ):
            try:
                for market in self._gamma_public_search_markets(query, limit):
                    key = self._gamma_market_key(market)
                    if key:
                        candidates[key] = self._gamma_merge_market_metadata(candidates.get(key, {}), market)
            except Exception as exc:
                cprint(f"Gamma public-search warning for '{query}': {exc}", "yellow")

        catalog = self._gamma_active_market_catalog(limit=max(limit * 10, 300))
        scored = []
        for market in catalog:
            score = self._gamma_market_query_score(market, query)
            if score <= 0:
                continue
            scored.append((score, market))

        scored.sort(key=lambda item: item[0], reverse=True)
        for _, market in scored[:limit]:
            key = self._gamma_market_key(market)
            if key:
                candidates[key] = self._gamma_merge_market_metadata(candidates.get(key, {}), market)

        prepared = [self._gamma_prepare_market_index(market) for market in candidates.values()]
        prepared.sort(
            key=lambda market: self._gamma_market_query_score(market, query),
            reverse=True,
        )
        return prepared[:limit]

    def _gamma_public_search_markets(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        payload = self._gamma_request(
            "/public-search",
            params={"q": query, "limit": limit},
        )
        markets: List[Dict[str, Any]] = []
        if isinstance(payload, dict):
            markets.extend(self._coerce_market_list(payload.get("markets")))
            events = payload.get("events")
            if isinstance(events, list):
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    event_markets = event.get("markets")
                    if not isinstance(event_markets, list):
                        continue
                    for market in event_markets:
                        if isinstance(market, dict):
                            markets.append(self._gamma_event_market_payload(event, market))
        elif isinstance(payload, list):
            markets.extend(self._coerce_market_list(payload))
        return markets

    def _gamma_list_markets(self, limit: int = 25, active: bool = True, order: str = "volume_num") -> List[Dict]:
        params: Dict[str, Any] = {
            "limit": limit,
            "active": str(active).lower(),
            "order": self._gamma_order_param(order),
        }
        if active:
            params["closed"] = "false"
        payload = self._gamma_request(
            "/markets",
            params=params,
        )
        return self._coerce_market_list(payload)

    def _gamma_get_market(self, market_id: str) -> Dict[str, Any]:
        try:
            payload = self._gamma_request(f"/markets/{market_id}")
        except Exception:
            target = str(market_id or "").strip()
            for market in self._gamma_active_market_catalog(limit=500):
                if target in {
                    str(market.get("conditionId", "")).strip(),
                    str(market.get("id", "")).strip(),
                    str(market.get("slug", "")).strip(),
                }:
                    return market
            raise
        if isinstance(payload, list):
            return payload[0] if payload else {}
        return payload if isinstance(payload, dict) else {}

    # =====================================================================
    # DIRECT API (py-clob-client)
    # =====================================================================

    def _init_clob_client(self):
        """Initialize py-clob-client for direct API access (bypasses geo-block)."""
        if not HAS_CLOB_CLIENT:
            reason = _CLOB_IMPORT_ERROR or "not installed"
            cprint(f"py-clob-client unavailable ({reason}) — using CLI binary", "yellow")
            return

        private_key = self.config.polymarket_private_key
        if not private_key:
            cprint("No POLYMARKET_PRIVATE_KEY — direct API disabled", "yellow")
            return

        try:
            from eth_account import Account
            eoa_address = Account.from_key(private_key).address
            self._eoa_address = eoa_address
            funder = self.config.polymarket_funder_address or eoa_address
            self._clob_client = ClobClient(
                host=self.config.polymarket_clob_url,
                key=private_key,
                chain_id=137,
                signature_type=2,
                funder=funder,
            )

            proxy_url = self.config.polymarket_proxy_url
            if proxy_url:
                import httpx
                import py_clob_client.http_helpers.helpers as clob_http
                clob_http._http_client = httpx.Client(http2=True, proxy=proxy_url)
                cprint(f"CLOB proxy configured: {proxy_url.split('@')[-1]}", "green")

            self._clob_client.set_api_creds(self._clob_client.derive_api_key())
            cprint("Direct API mode (py-clob-client) initialized", "green")
        except Exception as e:
            cprint(f"py-clob-client init failed: {e} — falling back to CLI", "yellow")
            self._clob_client = None

    # =====================================================================
    # STATUS / HEALTH CHECK
    # =====================================================================

    def get_health_status(self) -> Dict[str, Any]:
        """
        Structured status for orchestrator/preflight observability.
        """
        transport = "cli" if self.cli_available else (
            "direct_api" if bool(self._clob_client) else "missing"
        )
        status: Dict[str, Any] = {
            "cli_binary": self.binary,
            "cli_available": bool(self.cli_available),
            "cli_binary_check_error": self._cli_binary_check_error,
            "direct_api_available": bool(self._clob_client),
            "transport": transport,
            "config_sanity": "ok",
            "config_snapshot": {
                "execution_mode": self.config.execution_mode.value,
                "max_total_exposure_usd": self.config.max_total_exposure_usd,
                "max_position_usd": self.config.max_position_usd,
                "min_position_usd": self.config.min_position_usd,
                "cycle_interval_seconds": self.config.cycle_interval_seconds,
                "order_fill_timeout_seconds": self.config.order_fill_timeout_seconds,
            },
            "errors": [],
        }

        status_ok = False
        permission_failures: List[str] = []
        if self.cli_available:
            status_ok = self.check_status()
        elif self._clob_client:
            # Direct API mode: CLI may be unavailable in some environments.
            status_ok = True
        status["cli_status_ok"] = bool(status_ok)
        if not status_ok:
            status["errors"].append("cli_status_check_failed")
            permission_failures.append("transport_not_ready")

        address = self.get_wallet_address()
        status["wallet_configured"] = bool(address)
        status["wallet_address"] = address or ""
        if not status["wallet_configured"]:
            permission_failures.append("wallet_not_configured")

        balance = self.get_balance()
        if balance is None:
            status["balance_read_ok"] = False
            status["balance"] = 0.0
            permission_failures.append("balance_read_failed")
        else:
            parsed = (
                balance.get("balance", balance.get("amount"))
                if isinstance(balance, dict)
                else balance
            )
            balance_value = self._to_float(parsed)
            status["balance_read_ok"] = balance_value is not None
            status["balance"] = balance_value if balance_value is not None else 0.0

        required_balance = float(self.config.effective_live_balance_floor_usd)
        status["required_live_balance"] = required_balance
        status["permissions_ok"] = (
            bool(status["wallet_configured"])
            and bool(status["balance_read_ok"])
            and status["balance"] >= required_balance
        )
        if not status["permissions_ok"] and status["wallet_configured"]:
            status["errors"].append("insufficient balance for live mode floor")
            permission_failures.append("insufficient_balance_for_live_floor")

        status["config_sanity"] = (
            "ok"
            if self.config.max_total_exposure_usd >= self.config.max_position_usd >= self.config.min_position_usd
            else "invalid_risk_limits"
        )
        if status["config_sanity"] != "ok":
            status["errors"].append(status["config_sanity"])
            permission_failures.append(status["config_sanity"])

        status["permission_failures"] = permission_failures
        status["timestamp"] = time.time()
        return status

    def check_status(self) -> bool:
        """Backwards-compatible CLI status check."""
        if not self._cli_available:
            return bool(self._clob_client)

        result = self._execute(["status"], use_json=False)
        if not result.success:
            return False

        payload = (result.payload or "").strip()
        payload_lower = payload.lower()
        return ("ok" in payload_lower or "healthy" in payload_lower or "ready" in payload_lower)

    # =====================================================================
    # INTERNAL HELPERS
    # =====================================================================

    def _to_token(self, token_id: str) -> str:
        if token_id is None:
            return ""

        raw = str(token_id).strip()
        if not raw:
            return ""

        if raw.lower().startswith("0x"):
            try:
                return str(int(raw, 16))
            except ValueError:
                return raw

        if "." in raw:
            raw = raw.split(".", 1)[0]

        return raw

    # =====================================================================
    # MARKET DISCOVERY
    # =====================================================================

    def search_markets(self, query: str, limit: int = 50) -> Optional[List[Dict]]:
        return self._convert_cli_result(
            lambda: self._gamma_search_markets(query, limit),
            ["markets", "search", query, "--limit", str(limit)],
            "search_markets",
            allow_without_client=True,
        )

    def list_markets(self, limit: int = 25, active: bool = True,
                     order: str = "volume_num") -> Optional[List[Dict]]:
        args = ["markets", "list", "--limit", str(limit), "--order", order]
        if active:
            args += ["--active", "true"]
        return self._convert_cli_result(
            lambda: self._gamma_list_markets(limit=limit, active=active, order=order),
            args,
            "list_markets",
            allow_without_client=True,
        )

    def get_market(self, market_id: str) -> Optional[Dict]:
        return self._convert_cli_result(
            lambda: self._gamma_get_market(market_id),
            ["markets", "get", market_id],
            "get_market",
            allow_without_client=True,
        )

    # =====================================================================
    # EVENTS
    # =====================================================================

    def list_events(self, tag: Optional[str] = None, limit: int = 25,
                    active: bool = True) -> Optional[List[Dict]]:
        args = ["events", "list", "--limit", str(limit)]
        if tag:
            args += ["--tag", tag]
        if active:
            args += ["--active", "true"]
        return self._convert_cli_result(None, args, "list_events")

    def get_event(self, event_id: str) -> Optional[Dict]:
        return self._convert_cli_result(None, ["events", "get", event_id], "get_event")

    # =====================================================================
    # TAGS
    # =====================================================================

    def list_tags(self, limit: int = 100) -> Optional[List[Dict]]:
        return self._convert_cli_result(None, ["tags", "list", "--limit", str(limit)], "list_tags")

    # =====================================================================
    # CLOB - PRICING
    # =====================================================================

    def get_price(self, token_id: str, side: str = "buy") -> Optional[Dict]:
        def direct():
            return self._clob_client.get_price(self._to_token(token_id), side)
        return self._convert_cli_result(direct, ["clob", "price", token_id, "--side", side], "get_price")

    def get_midpoint(self, token_id: str) -> Optional[Any]:
        def direct():
            return self._clob_client.get_midpoint(self._to_token(token_id))
        return self._convert_cli_result(direct, ["clob", "midpoint", token_id], "get_midpoint")

    def get_midpoints(self, token_ids: List[str]) -> Optional[Any]:
        return self._convert_cli_result(
            None,
            ["clob", "midpoints", ",".join(token_ids)],
            "get_midpoints",
        )

    def get_spread(self, token_id: str) -> Optional[Dict]:
        return self._convert_cli_result(None, ["clob", "spread", token_id], "get_spread")

    def get_spreads(self, token_ids: List[str]) -> Optional[Any]:
        return self._convert_cli_result(None, ["clob", "spreads", ",".join(token_ids)], "get_spreads")

    def get_order_book(self, token_id: str) -> Optional[Dict]:
        def direct():
            book = self._clob_client.get_order_book(self._to_token(token_id))
            if hasattr(book, "__dataclass_fields__"):
                return book.__dict__
            return book
        return self._convert_cli_result(direct, ["clob", "book", token_id], "get_order_book")

    def get_last_trade(self, token_id: str) -> Optional[Dict]:
        return self._convert_cli_result(None, ["clob", "last-trade", token_id], "get_last_trade")

    def get_price_history(self, token_id: str, interval: str = "1h",
                         fidelity: Optional[int] = None) -> Optional[Any]:
        args = ["clob", "price-history", token_id, "--interval", interval]
        if fidelity:
            args += ["--fidelity", str(fidelity)]
        return self._convert_cli_result(None, args, "get_price_history")

    def get_tick_size(self, token_id: str) -> Optional[Any]:
        def direct():
            return self._clob_client.get_tick_size(self._to_token(token_id))
        return self._convert_cli_result(direct, ["clob", "tick-size", token_id], "get_tick_size")

    def get_clob_market(self, condition_id: str) -> Optional[Dict]:
        return self._convert_cli_result(
            lambda: self._gamma_get_market(condition_id),
            ["clob", "market", condition_id],
            "get_clob_market",
            allow_without_client=True,
        )

    # =====================================================================
    # CLOB - TRADING (Auth Required)
    # =====================================================================

    def create_limit_order(self, token_id: str, side: str, price: float,
                          size: float, order_type: str = "GTC") -> Optional[Dict]:
        def direct():
            clob_side = BUY if side.upper() == "BUY" else SELL
            normalized_order_type = str(order_type or "GTC").upper()
            clob_order_type = (
                getattr(OrderType, normalized_order_type, OrderType.GTC)
                if OrderType is not None
                else normalized_order_type
            )
            order = self._clob_client.create_order(
                OrderArgs(
                    token_id=self._to_token(token_id),
                    price=price,
                    size=size,
                    side=clob_side,
                )
            )
            return self._clob_client.post_order(order, orderType=clob_order_type)
        return self._convert_cli_result(
            direct,
            [
                "clob",
                "create-order",
                "--token",
                token_id,
                "--side",
                side,
                "--price",
                str(price),
                "--size",
                str(size),
                "--order-type",
                order_type,
            ],
            source_name="create_limit_order",
        )

    def create_market_order(self, token_id: str, side: str,
                           amount: float) -> Optional[Dict]:
        def direct():
            clob_side = BUY if side.upper() == "BUY" else SELL
            aggressive_price = 0.99 if clob_side == BUY else 0.01
            return self._clob_client.create_and_post_order(
                OrderArgs(
                    token_id=self._to_token(token_id),
                    price=aggressive_price,
                    size=amount,
                    side=clob_side,
                )
            )
        return self._convert_cli_result(
            direct,
            [
                "clob",
                "market-order",
                "--token",
                token_id,
                "--side",
                side,
                "--amount",
                str(amount),
            ],
            source_name="create_market_order",
        )

    def get_open_orders(self, market: Optional[str] = None) -> Optional[List[Dict]]:
        def direct():
            orders = self._clob_client.get_orders()
            if not market:
                return orders if orders else []

            token_filter = str(market).lower()
            normalized_orders = []
            for order in orders or []:
                token_id = str(order.get("token_id", order.get("asset_id", ""))).lower()
                market_id = str(order.get("market", order.get("market_id", ""))).lower()
                if token_id == token_filter or market_id == token_filter:
                    normalized_orders.append(order)
            return normalized_orders
        args = ["clob", "orders"]
        if market:
            args += ["--market", market]
        return self._convert_cli_result(direct, args, "get_open_orders")

    def cancel_order(self, order_id: str) -> Optional[Dict]:
        def direct():
            return self._clob_client.cancel(order_id)
        return self._convert_cli_result(direct, ["clob", "cancel", order_id], "cancel_order")

    def cancel_all_orders(self) -> Optional[Dict]:
        def direct():
            return self._clob_client.cancel_all()
        return self._convert_cli_result(direct, ["clob", "cancel-all"], "cancel_all_orders")

    def get_balance(self, asset_type: str = "collateral",
                    token_id: Optional[str] = None) -> Optional[Dict]:
        def direct():
            return self._clob_client.get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
        return self._convert_cli_result(direct, ["clob", "balance", "--asset-type", asset_type], "get_balance")

    def get_trades(self, market: Optional[str] = None) -> Optional[List[Dict]]:
        def direct():
            trades = self._clob_client.get_trades()
            if not market:
                return trades if trades else []
            market_id = str(market).lower()
            return [
                t for t in (trades or [])
                if str(t.get("market", t.get("asset_id", ""))).lower() == market_id
            ]

        args = ["clob", "trades"]
        if market:
            args += ["--market", market]
        return self._convert_cli_result(direct, args, "get_trades")

    # =====================================================================
    # DATA - ANALYTICS
    # =====================================================================

    def get_positions(self, address: str, limit: int = 25) -> Optional[List[Dict]]:
        return self._convert_cli_result(
            None,
            ["data", "positions", address, "--limit", str(limit)],
            "get_positions",
        )

    def get_leaderboard(self, period: str = "week", order_by: str = "pnl",
                        limit: int = 25) -> Optional[List[Dict]]:
        return self._convert_cli_result(
            None,
            [
                "data",
                "leaderboard",
                "--period",
                period,
                "--order-by",
                order_by,
                "--limit",
                str(limit),
            ],
            "get_leaderboard",
        )

    def get_open_interest(self, condition_id: str) -> Optional[Dict]:
        return self._convert_cli_result(None, ["data", "open-interest", condition_id], "get_open_interest")

    def get_volume(self, event_id: str) -> Optional[Dict]:
        return self._convert_cli_result(None, ["data", "volume", event_id], "get_volume")

    def get_holders(self, condition_id: str, limit: int = 10) -> Optional[List[Dict]]:
        return self._convert_cli_result(
            None,
            ["data", "holders", condition_id, "--limit", str(limit)],
            "get_holders",
        )

    # =====================================================================
    # WALLET
    # =====================================================================

    def get_wallet_address(self) -> Optional[str]:
        if self.cli_available:
            result = self._execute(["wallet", "address"], use_json=False)
            if not result.success:
                cprint(f"Wallet query failed: {result.error}", "yellow")
            else:
                payload = str(result.payload or "")
                for line in payload.split("\\n"):
                    line = line.strip()
                    if line.startswith("0x"):
                        return line

        if self._eoa_address:
            return self._eoa_address

        if self._clob_client is not None:
            for key in ("account", "wallet", "address", "user"):
                if hasattr(self._clob_client, key):
                    candidate = getattr(self._clob_client, key)
                    if isinstance(candidate, str) and candidate.startswith("0x"):
                        return candidate
                    if isinstance(candidate, object) and hasattr(candidate, "address"):
                        maybe = getattr(candidate, "address")
                        if isinstance(maybe, str) and maybe.startswith("0x"):
                            return maybe
        return None

    @property
    def stats(self) -> Dict[str, int]:
        """Return CLI usage stats."""
        return {"total_calls": self._call_count}

    # Optional compatibility shim for older imports.
    def is_cli_available(self) -> bool:
        return bool(self.cli_available)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Polymarket CLI wrapper diagnostics")
    parser.add_argument("--status", action="store_true", help="Print health status")
    args = parser.parse_args()

    cli = PolymarketCLI()
    if args.status:
        from pprint import pprint
        pprint(cli.get_health_status())
    else:
        print(f"\\nAPI Status: {cli.check_status()}")
        print(f"CLI calls: {cli.stats}")
        print(f"CLI available: {cli.cli_available}")
