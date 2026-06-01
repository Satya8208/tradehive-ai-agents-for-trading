"""
Polymarket CLI Trading Agent Configuration

All settings for the CLI-based Polymarket trading system.
Supports DRY_RUN, PAPER, and LIVE execution modes.
"""

import math
import os
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
from termcolor import cprint
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
SCHEMA_VERSION = 5

def _default_cli_binary() -> str:
    explicit = os.getenv("POLYMARKET_CLI_BINARY") or os.getenv("PM_CLI_BINARY")
    if explicit:
        return explicit

    local_binary = Path.home() / ".local" / "bin" / "polymarket"
    if local_binary.exists():
        return str(local_binary)

    path_binary = shutil.which("polymarket")
    if path_binary:
        return path_binary

    if os.name == "nt":
        return "polymarket"
    return "/usr/local/bin/polymarket"


class ExecutionMode(str, Enum):
    DRY_RUN = "dry_run"
    PAPER = "paper"
    LIVE = "live"


class TradeSide(str, Enum):
    YES = "YES"
    NO = "NO"


def _normalize_execution_mode(raw: Optional[str]) -> ExecutionMode:
    if isinstance(raw, ExecutionMode):
        return raw

    if hasattr(raw, "value"):
        candidate = getattr(raw, "value")
        if candidate in {m.value for m in ExecutionMode}:
            return ExecutionMode(candidate)

    if raw is None:
        return ExecutionMode.DRY_RUN

    try:
        return ExecutionMode(str(raw).strip().lower())
    except ValueError:
        cprint(
            f"Invalid PM_CLI_EXECUTION_MODE='{raw}' (expected dry_run|paper|live). "
            "Falling back to dry_run.",
            "yellow",
        )
        return ExecutionMode.DRY_RUN


def _coerce_positive_float(
    value,
    default: float,
    name: str,
    *,
    min_value: float = 0.0,
    max_value: Optional[float] = None,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        cprint(
            f"Invalid float for {name}: {value!r}; using default {default}",
            "yellow",
        )
        return float(default)

    if not math.isfinite(parsed):
        cprint(
            f"Non-finite value for {name}: {value!r}; using default {default}",
            "yellow",
        )
        return float(default)

    if parsed < min_value:
        return float(min_value)
    if max_value is not None and parsed > max_value:
        return float(max_value)
    return parsed


def _coerce_positive_int(
    value,
    default: int,
    name: str,
    *,
    min_value: int = 1,
    max_value: Optional[int] = None,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        cprint(
            f"Invalid int for {name}: {value!r}; using default {default}",
            "yellow",
        )
        return int(default)

    if parsed < min_value:
        return int(min_value)
    if max_value is not None and parsed > max_value:
        return int(max_value)
    return int(parsed)


def _coerce_bool(value, default: bool, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_path(path_value: str, fallback: str) -> str:
    expanded = str(Path(path_value or fallback).expanduser())
    if os.name == "nt":
        # Handle WSL-like or POSIX absolute paths on Windows hosts.
        if str(expanded).startswith("/"):
            fallback_name = Path(expanded).name
            if fallback_name and fallback_name != expanded:
                cprint(
                    f"Normalized non-Windows CLI path '{expanded}' to '{fallback_name}'",
                    "yellow",
                )
                expanded = fallback_name

    if not Path(expanded).is_absolute():
        path_obj = Path(expanded)
        if os.name == "nt" and path_obj.name == expanded:
            return expanded
        expanded = str((Path.cwd() / path_obj).resolve())
    return expanded


@dataclass
class PolymarketCLIConfig:
    """Configuration for Polymarket CLI trading agents."""

    # CLI settings
    cli_binary: str = field(default_factory=_default_cli_binary)
    cli_timeout_seconds: int = 30
    cli_rate_limit_ms: int = 200
    cli_retry_count: int = 2
    cli_retry_backoff_seconds: float = 0.5

    # Direct API
    use_direct_api: bool = True
    polymarket_clob_url: str = "https://clob.polymarket.com"
    polymarket_gamma_url: str = field(
        default_factory=lambda: os.getenv("POLYMARKET_GAMMA_URL", "https://gamma-api.polymarket.com")
    )
    polymarket_private_key: str = field(
        default_factory=lambda: os.getenv("POLYMARKET_PRIVATE_KEY", "")
    )
    polymarket_funder_address: str = field(
        default_factory=lambda: os.getenv("POLYMARKET_FUNDER_ADDRESS", "")
    )
    polymarket_proxy_url: str = field(
        default_factory=lambda: os.getenv("POLYMARKET_PROXY_URL", "")
    )

    # Execution
    execution_mode: ExecutionMode = field(
        default_factory=lambda: _normalize_execution_mode(os.getenv("PM_CLI_EXECUTION_MODE", "dry_run"))
    )
    market_vertical: str = field(
        default_factory=lambda: os.getenv("PM_MARKET_VERTICAL", "crypto")
    )

    # Market discovery
    search_symbols: list = field(default_factory=lambda: ["ETH"])
    enforce_search_symbol_filter: bool = True
    crypto_keywords: list = field(
        default_factory=lambda: [
            "ethereum",
            "eth",
            "ether",
            "crypto",
            "up or down",
        ]
    )
    min_liquidity_usd: float = 10000.0
    min_volume_24h_usd: float = 5000.0
    max_markets_to_analyze: int = 5
    market_cache_seconds: int = 300
    max_expiry_hours: Optional[float] = 24.0
    min_expiry_hours: Optional[float] = None
    min_expiry_minutes: float = 30.0
    weather_locations: list = field(
        default_factory=lambda: [
            "New York City",
            "Chicago",
            "Miami",
            "Austin",
            "Los Angeles",
            "Philadelphia",
            "Boston",
            "Washington DC",
            "Denver",
            "Dallas",
            "Houston",
            "San Francisco",
            "Phoenix",
            "Atlanta",
            "London",
        ]
    )
    weather_search_terms: list = field(
        default_factory=lambda: [
            "weather",
            "temperature",
            "rain",
            "snow",
            "wind",
            "hurricane",
            "tropical storm",
            "space weather",
        ]
    )
    weather_forecast_days: int = 16
    weather_min_probability_gap: float = 0.08
    max_weather_search_queries: int = 12
    weather_require_alpha_verification: bool = False
    weather_alpha_report_path: str = ""
    weather_high_resolution_sources: list = field(default_factory=lambda: ["noaa_hrrr", "noaa_nbm"])
    weather_high_resolution_cache_dir: str = ""
    weather_auto_ingest_high_resolution: bool = False
    weather_high_resolution_min_request_interval_seconds: float = 10.0
    weather_high_resolution_timeout_seconds: int = 60
    weather_station_bias_path: str = ""
    weather_require_high_resolution_confirmation: bool = False
    weather_require_station_bias_validation: bool = False
    weather_max_selected_source_age_minutes: float = 180.0
    weather_evidence_enabled: bool = True
    weather_market_tape_fetch_orderbook: bool = False
    weather_market_tape_fetch_last_trade: bool = False
    weather_evidence_min_resolved_markets: int = 50
    weather_evidence_min_trade_decisions: int = 20
    weather_ai_forecast_engine_enabled: bool = True
    weather_ai_lead_provider: str = "openai"
    weather_ai_lead_model: str = "gpt-5.5"
    weather_ai_autonomy_mode: str = "paper_only"
    weather_ai_decision_required: bool = False
    weather_ai_max_tokens: int = 900
    weather_previous_run_lead_days: int = 1
    weather_previous_run_past_days: int = 7
    allow_live_weather_trading: bool = False
    weather_release_certificate_path: str = ""

    # Swarm
    swarm_models: list = field(
        default_factory=lambda: [
            ("openai", "gpt-5.5"),
            ("deepseek", "deepseek-v4-pro"),
            ("xai", "grok-4.3"),
        ]
    )
    swarm_timeout_seconds: int = 90
    min_consensus_count: int = 2
    min_consensus_confidence: float = 0.50

    # Strategy
    kelly_fraction: float = 0.15
    min_edge_threshold: float = 15.0
    min_edge_confidence: float = 0.50
    time_decay_half_life_hours: float = 2.0
    time_decay_minimum: float = 0.10

    # Arbitrage
    min_arb_edge_percent: float = 27.0
    arb_fee_estimate_percent: float = 1.0
    arb_fuzzy_match_threshold: float = 0.7
    min_arb_token_price: float = 0.05
    max_arb_capital_pct: float = 0.30

    # Risk
    max_position_usd: float = 30.0
    max_total_exposure_usd: float = 300.0
    min_position_usd: float = 5.0
    max_positions: int = 4
    max_positions_per_symbol: int = 4
    max_positions_per_direction: int = 3
    max_per_market_usd: float = 30.0
    max_daily_trades: int = 50
    daily_loss_limit_usd: float = 50.0

    # Paper
    paper_starting_balance: float = 1000.0

    # Live
    order_fill_timeout_seconds: int = 30
    max_slippage_pct: float = 2.0
    live_max_position_usd: float = 5.0
    live_min_balance_usd: float = 2.0
    live_balance_reserve_usd: float = 5.0
    unrealized_loss_limit_usd: float = 50.0
    live_order_stale_seconds: int = 300

    # Timing
    cycle_interval_seconds: int = 60

    # Whale
    whale_leaderboard_top_n: int = 20
    whale_scan_interval_cycles: int = 6

    # Internal
    _data_dir_override: Optional[Path] = field(default=None, repr=False)
    crypto_search_queries: list = field(default_factory=list, init=False, repr=False)

    def __post_init__(self):
        self.execution_mode = _normalize_execution_mode(self.execution_mode)
        self.market_vertical = str(getattr(self, "market_vertical", "crypto") or "crypto").strip().lower()
        if self.market_vertical not in {"crypto", "weather"}:
            cprint(
                f"Invalid PM_MARKET_VERTICAL='{self.market_vertical}' (expected crypto|weather). "
                "Falling back to crypto.",
                "yellow",
            )
            self.market_vertical = "crypto"
        self.cli_binary = _normalize_path(self.cli_binary, _default_cli_binary())
        if isinstance(self._data_dir_override, str):
            self._data_dir_override = Path(self._data_dir_override).expanduser()

        self.cli_timeout_seconds = _coerce_positive_int(
            self.cli_timeout_seconds, default=30, name="cli_timeout_seconds", min_value=1
        )
        self.cli_rate_limit_ms = _coerce_positive_int(
            self.cli_rate_limit_ms, default=200, name="cli_rate_limit_ms", min_value=0
        )
        self.cli_retry_count = _coerce_positive_int(
            self.cli_retry_count, default=2, name="cli_retry_count", min_value=0, max_value=5
        )
        self.cli_retry_backoff_seconds = _coerce_positive_float(
            self.cli_retry_backoff_seconds,
            default=0.5,
            name="cli_retry_backoff_seconds",
            min_value=0.0,
            max_value=15.0,
        )

        self.min_liquidity_usd = _coerce_positive_float(
            self.min_liquidity_usd, 10000.0, "min_liquidity_usd", min_value=0.0
        )
        self.min_volume_24h_usd = _coerce_positive_float(
            self.min_volume_24h_usd, 5000.0, "min_volume_24h_usd", min_value=0.0
        )
        self.max_markets_to_analyze = _coerce_positive_int(
            self.max_markets_to_analyze, 5, "max_markets_to_analyze", min_value=1
        )
        self.market_cache_seconds = _coerce_positive_int(
            self.market_cache_seconds, 300, "market_cache_seconds", min_value=10
        )
        raw_symbols = list(getattr(self, "search_symbols", ["ETH"]) or [])
        if self.market_vertical == "weather" and raw_symbols == ["ETH"]:
            raw_symbols = ["WEATHER"]
        self.search_symbols = [
            str(s).strip().upper()
            for s in raw_symbols
            if str(s).strip()
        ] or (["WEATHER"] if self.market_vertical == "weather" else ["ETH"])
        self.search_symbols = list(dict.fromkeys(self.search_symbols))
        self.enforce_search_symbol_filter = _coerce_bool(
            getattr(self, "enforce_search_symbol_filter", True),
            True,
            "enforce_search_symbol_filter",
        )
        self.crypto_keywords = [
            str(k).strip().lower()
            for k in getattr(self, "crypto_keywords", ["crypto"])
            if str(k).strip()
        ]
        self.crypto_keywords = list(dict.fromkeys(self.crypto_keywords))
        self.max_expiry_hours = (
            _coerce_positive_float(
                self.max_expiry_hours, 24.0, "max_expiry_hours", min_value=0.1
            )
            if self.max_expiry_hours is not None
            else None
        )
        self.min_expiry_hours = (
            _coerce_positive_float(
                self.min_expiry_hours, 0.0, "min_expiry_hours", min_value=0.0
            )
            if self.min_expiry_hours is not None
            else None
        )
        self.min_expiry_minutes = _coerce_positive_float(
            self.min_expiry_minutes, 30.0, "min_expiry_minutes", min_value=0.0
        )
        self.weather_locations = [
            str(location).strip()
            for location in getattr(self, "weather_locations", [])
            if str(location).strip()
        ]
        self.weather_locations = list(dict.fromkeys(self.weather_locations))
        self.weather_search_terms = [
            str(term).strip().lower()
            for term in getattr(self, "weather_search_terms", [])
            if str(term).strip()
        ]
        self.weather_search_terms = list(dict.fromkeys(self.weather_search_terms))
        self.weather_forecast_days = _coerce_positive_int(
            self.weather_forecast_days,
            16,
            "weather_forecast_days",
            min_value=1,
            max_value=16,
        )
        self.max_weather_search_queries = _coerce_positive_int(
            self.max_weather_search_queries,
            12,
            "max_weather_search_queries",
            min_value=1,
            max_value=100,
        )
        self.weather_min_probability_gap = _coerce_positive_float(
            self.weather_min_probability_gap,
            0.08,
            "weather_min_probability_gap",
            min_value=0.0,
            max_value=1.0,
        )
        self.weather_high_resolution_sources = [
            str(source).strip().lower().replace("-", "_")
            for source in getattr(self, "weather_high_resolution_sources", [])
            if str(source).strip()
        ]
        self.weather_high_resolution_sources = list(dict.fromkeys(self.weather_high_resolution_sources))
        raw_high_res_cache_dir = str(getattr(self, "weather_high_resolution_cache_dir", "") or "").strip()
        self.weather_high_resolution_cache_dir = (
            str(Path(raw_high_res_cache_dir).expanduser()) if raw_high_res_cache_dir else ""
        )
        self.weather_auto_ingest_high_resolution = _coerce_bool(
            self.weather_auto_ingest_high_resolution,
            False,
            "weather_auto_ingest_high_resolution",
        )
        self.weather_high_resolution_min_request_interval_seconds = _coerce_positive_float(
            self.weather_high_resolution_min_request_interval_seconds,
            10.0,
            "weather_high_resolution_min_request_interval_seconds",
            min_value=0.0,
            max_value=300.0,
        )
        self.weather_high_resolution_timeout_seconds = _coerce_positive_int(
            self.weather_high_resolution_timeout_seconds,
            60,
            "weather_high_resolution_timeout_seconds",
            min_value=5,
            max_value=300,
        )
        self.weather_require_alpha_verification = _coerce_bool(
            self.weather_require_alpha_verification,
            False,
            "weather_require_alpha_verification",
        )
        self.weather_require_high_resolution_confirmation = _coerce_bool(
            self.weather_require_high_resolution_confirmation,
            False,
            "weather_require_high_resolution_confirmation",
        )
        self.weather_require_station_bias_validation = _coerce_bool(
            self.weather_require_station_bias_validation,
            False,
            "weather_require_station_bias_validation",
        )
        self.weather_station_bias_path = str(getattr(self, "weather_station_bias_path", "") or "").strip()
        self.weather_max_selected_source_age_minutes = _coerce_positive_float(
            self.weather_max_selected_source_age_minutes,
            180.0,
            "weather_max_selected_source_age_minutes",
            min_value=0.0,
        )
        self.weather_evidence_enabled = _coerce_bool(
            self.weather_evidence_enabled,
            True,
            "weather_evidence_enabled",
        )
        self.weather_market_tape_fetch_orderbook = _coerce_bool(
            self.weather_market_tape_fetch_orderbook,
            False,
            "weather_market_tape_fetch_orderbook",
        )
        self.weather_market_tape_fetch_last_trade = _coerce_bool(
            self.weather_market_tape_fetch_last_trade,
            False,
            "weather_market_tape_fetch_last_trade",
        )
        self.weather_evidence_min_resolved_markets = _coerce_positive_int(
            self.weather_evidence_min_resolved_markets,
            50,
            "weather_evidence_min_resolved_markets",
            min_value=1,
        )
        self.weather_evidence_min_trade_decisions = _coerce_positive_int(
            self.weather_evidence_min_trade_decisions,
            20,
            "weather_evidence_min_trade_decisions",
            min_value=1,
        )
        self.weather_ai_forecast_engine_enabled = _coerce_bool(
            self.weather_ai_forecast_engine_enabled,
            True,
            "weather_ai_forecast_engine_enabled",
        )
        self.weather_ai_lead_provider = str(
            getattr(self, "weather_ai_lead_provider", "openai") or "openai"
        ).strip().lower()
        self.weather_ai_lead_model = str(
            getattr(self, "weather_ai_lead_model", "gpt-5.5") or "gpt-5.5"
        ).strip()
        self.weather_ai_autonomy_mode = str(
            getattr(self, "weather_ai_autonomy_mode", "paper_only") or "paper_only"
        ).strip().lower()
        if self.weather_ai_autonomy_mode not in {"paper_only", "disabled"}:
            cprint(
                f"Invalid weather_ai_autonomy_mode='{self.weather_ai_autonomy_mode}'. "
                "Falling back to paper_only.",
                "yellow",
            )
            self.weather_ai_autonomy_mode = "paper_only"
        self.weather_ai_decision_required = _coerce_bool(
            self.weather_ai_decision_required,
            False,
            "weather_ai_decision_required",
        )
        self.weather_ai_max_tokens = _coerce_positive_int(
            self.weather_ai_max_tokens,
            900,
            "weather_ai_max_tokens",
            min_value=128,
            max_value=4000,
        )
        self.weather_previous_run_lead_days = _coerce_positive_int(
            self.weather_previous_run_lead_days,
            1,
            "weather_previous_run_lead_days",
            min_value=1,
            max_value=7,
        )
        self.weather_previous_run_past_days = _coerce_positive_int(
            self.weather_previous_run_past_days,
            7,
            "weather_previous_run_past_days",
            min_value=1,
            max_value=16,
        )
        self.allow_live_weather_trading = _coerce_bool(
            self.allow_live_weather_trading,
            False,
            "allow_live_weather_trading",
        )
        self.weather_release_certificate_path = str(
            getattr(self, "weather_release_certificate_path", "") or ""
        ).strip()

        self.swarm_timeout_seconds = _coerce_positive_int(
            self.swarm_timeout_seconds, 90, "swarm_timeout_seconds", min_value=5, max_value=300
        )
        self.min_consensus_count = _coerce_positive_int(
            self.min_consensus_count, 2, "min_consensus_count", min_value=1
        )
        self.min_consensus_confidence = _coerce_positive_float(
            self.min_consensus_confidence,
            0.50,
            "min_consensus_confidence",
            min_value=0.0,
            max_value=1.0,
        )
        self.kelly_fraction = _coerce_positive_float(
            self.kelly_fraction, 0.15, "kelly_fraction", min_value=0.0, max_value=1.0
        )
        self.min_edge_threshold = _coerce_positive_float(
            self.min_edge_threshold, 15.0, "min_edge_threshold", min_value=0.0
        )
        self.min_edge_confidence = _coerce_positive_float(
            self.min_edge_confidence, 0.50, "min_edge_confidence", min_value=0.0, max_value=1.0
        )
        self.time_decay_half_life_hours = _coerce_positive_float(
            self.time_decay_half_life_hours, 2.0, "time_decay_half_life_hours", min_value=0.01
        )
        self.time_decay_minimum = _coerce_positive_float(
            self.time_decay_minimum, 0.10, "time_decay_minimum", min_value=0.001, max_value=1.0
        )

        self.min_arb_edge_percent = _coerce_positive_float(
            self.min_arb_edge_percent, 27.0, "min_arb_edge_percent", min_value=0.0
        )
        self.arb_fee_estimate_percent = _coerce_positive_float(
            self.arb_fee_estimate_percent, 1.0, "arb_fee_estimate_percent", min_value=0.0
        )
        self.arb_fuzzy_match_threshold = _coerce_positive_float(
            self.arb_fuzzy_match_threshold, 0.7, "arb_fuzzy_match_threshold", min_value=0.0, max_value=1.0
        )
        self.min_arb_token_price = _coerce_positive_float(
            self.min_arb_token_price, 0.05, "min_arb_token_price", min_value=0.0
        )
        self.max_arb_capital_pct = _coerce_positive_float(
            self.max_arb_capital_pct, 0.30, "max_arb_capital_pct", min_value=0.0, max_value=1.0
        )

        self.max_position_usd = _coerce_positive_float(
            self.max_position_usd, 30.0, "max_position_usd", min_value=0.0
        )
        self.max_total_exposure_usd = _coerce_positive_float(
            self.max_total_exposure_usd,
            300.0,
            "max_total_exposure_usd",
            min_value=max(self.max_position_usd, 0.01),
        )
        self.min_position_usd = _coerce_positive_float(
            self.min_position_usd, 5.0, "min_position_usd", min_value=0.0
        )
        self.max_positions = _coerce_positive_int(
            self.max_positions, 4, "max_positions", min_value=1
        )
        self.max_positions_per_symbol = _coerce_positive_int(
            self.max_positions_per_symbol, 4, "max_positions_per_symbol", min_value=1
        )
        self.max_positions_per_direction = _coerce_positive_int(
            self.max_positions_per_direction, 3, "max_positions_per_direction", min_value=1
        )
        self.max_per_market_usd = _coerce_positive_float(
            self.max_per_market_usd, 30.0, "max_per_market_usd", min_value=0.0
        )
        self.max_daily_trades = _coerce_positive_int(
            self.max_daily_trades, 50, "max_daily_trades", min_value=1
        )
        self.daily_loss_limit_usd = _coerce_positive_float(
            self.daily_loss_limit_usd, 50.0, "daily_loss_limit_usd", min_value=0.0
        )

        self.paper_starting_balance = _coerce_positive_float(
            self.paper_starting_balance, 1000.0, "paper_starting_balance", min_value=0.0
        )
        self.order_fill_timeout_seconds = _coerce_positive_int(
            self.order_fill_timeout_seconds, 30, "order_fill_timeout_seconds", min_value=1
        )
        self.max_slippage_pct = _coerce_positive_float(
            self.max_slippage_pct, 2.0, "max_slippage_pct", min_value=0.0
        )
        self.live_max_position_usd = _coerce_positive_float(
            self.live_max_position_usd, 5.0, "live_max_position_usd", min_value=0.0
        )
        self.live_min_balance_usd = _coerce_positive_float(
            self.live_min_balance_usd, 2.0, "live_min_balance_usd", min_value=0.0
        )
        self.live_balance_reserve_usd = _coerce_positive_float(
            self.live_balance_reserve_usd, 5.0, "live_balance_reserve_usd", min_value=0.0
        )
        self.unrealized_loss_limit_usd = _coerce_positive_float(
            self.unrealized_loss_limit_usd, 50.0, "unrealized_loss_limit_usd", min_value=0.0
        )
        self.live_order_stale_seconds = _coerce_positive_int(
            self.live_order_stale_seconds, 300, "live_order_stale_seconds", min_value=30
        )

        self.cycle_interval_seconds = _coerce_positive_int(
            self.cycle_interval_seconds, 60, "cycle_interval_seconds", min_value=5
        )
        self.whale_leaderboard_top_n = _coerce_positive_int(
            self.whale_leaderboard_top_n, 20, "whale_leaderboard_top_n", min_value=1
        )
        self.whale_scan_interval_cycles = _coerce_positive_int(
            self.whale_scan_interval_cycles, 6, "whale_scan_interval_cycles", min_value=1
        )

        # Keep derived defaults stable and conservative.
        if self.min_position_usd > self.max_position_usd:
            self.min_position_usd = self.max_position_usd
        if self.max_position_usd > self.max_total_exposure_usd:
            self.max_position_usd = self.max_total_exposure_usd
        if self.max_per_market_usd <= 0.0:
            self.max_per_market_usd = self.max_position_usd
        if self.max_per_market_usd > 0 and self.max_per_market_usd < self.max_position_usd:
            self.max_per_market_usd = self.max_position_usd

        name_map = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
            "XRP": "xrp",
            "DOGE": "dogecoin",
            "ADA": "cardano",
            "AVAX": "avalanche",
            "LINK": "chainlink",
            "DOT": "polkadot",
        }
        if self.market_vertical == "weather":
            queries = []
            for term in self.weather_search_terms:
                queries.append((term, "WEATHER"))
            for location in self.weather_locations:
                queries.extend(
                    [
                        (f"{location} weather", "WEATHER"),
                        (f"{location} temperature", "WEATHER"),
                        (f"{location} rain", "WEATHER"),
                    ]
                )
        else:
            queries = [("crypto", "CRYPTO")]
            for sym in self.search_symbols:
                name = name_map.get(sym, str(sym).lower())
                queries.extend(
                    [
                        (name, str(sym)),
                        (f"{str(sym).lower()} price", str(sym)),
                        (f"{name} up or down", str(sym)),
                        (f"{str(sym).lower()} above", str(sym)),
                    ]
                )
        self.crypto_search_queries = queries

    @property
    def data_dir(self) -> Path:
        if self._data_dir_override is not None:
            return self._data_dir_override.expanduser().resolve()
        return PROJECT_ROOT / "src" / "data" / "polymarket_trader"

    @property
    def effective_live_max_position_usd(self) -> float:
        live_cap = _coerce_positive_float(
            self.live_max_position_usd, self.max_position_usd, "live_max_position_usd", min_value=0.0
        )
        if live_cap <= 0:
            return self.max_position_usd
        return min(live_cap, self.max_position_usd)

    @property
    def effective_live_balance_floor_usd(self) -> float:
        return max(
            self.live_min_balance_usd,
            self.max_total_exposure_usd + self.effective_live_max_position_usd + self.live_balance_reserve_usd,
        )

    def live_available_balance_guard_usd(self, balance_usd: float) -> float:
        return max(0.0, _coerce_positive_float(balance_usd, 0.0, "balance_usd", min_value=0.0) - self.live_balance_reserve_usd)

    @property
    def markets_dir(self) -> Path:
        return self.data_dir / "markets"

    @property
    def trades_dir(self) -> Path:
        return self.data_dir / "trades"

    @property
    def predictions_dir(self) -> Path:
        return self.data_dir / "predictions"

    @property
    def positions_dir(self) -> Path:
        return self.data_dir / "positions"

    @property
    def arbitrage_dir(self) -> Path:
        return self.data_dir / "arbitrage"

    @property
    def cycles_dir(self) -> Path:
        return self.data_dir / "cycles"

    @property
    def whales_dir(self) -> Path:
        return self.data_dir / "whales"

    def ensure_dirs(self):
        for d in [
            self.data_dir,
            self.markets_dir,
            self.trades_dir,
            self.predictions_dir,
            self.positions_dir,
            self.arbitrage_dir,
            self.cycles_dir,
            self.whales_dir,
            self.data_dir / "weather_evidence",
        ]:
            d.mkdir(parents=True, exist_ok=True)


def get_polymarket_cli_config(**kwargs) -> PolymarketCLIConfig:
    """Factory helper for explicitly building a validated config."""
    return PolymarketCLIConfig(**kwargs)


default_config = PolymarketCLIConfig()


def get_config() -> PolymarketCLIConfig:
    return default_config


def get_schema_version() -> int:
    return SCHEMA_VERSION


def get_config_snapshot() -> dict:
    cfg = get_config()
    return {
        "execution_mode": cfg.execution_mode.value,
        "market_vertical": cfg.market_vertical,
        "cli_binary": cfg.cli_binary,
        "max_total_exposure_usd": cfg.max_total_exposure_usd,
        "max_position_usd": cfg.max_position_usd,
        "schema_version": SCHEMA_VERSION,
    }
