from pathlib import Path

from src.agents.polymarket_trader.config import ExecutionMode, get_polymarket_cli_config


def test_invalid_execution_mode_falls_back_to_dry_run():
    cfg = get_polymarket_cli_config(execution_mode="invalid_mode")
    assert cfg.execution_mode == ExecutionMode.DRY_RUN


def test_numeric_and_path_coercion_and_limits():
    cfg = get_polymarket_cli_config(
        cli_binary="bin/polymarket",
        cli_timeout_seconds="n/a",
        cli_rate_limit_ms="n/a",
        cli_retry_count=-3,
        cli_retry_backoff_seconds="bad",
        order_fill_timeout_seconds="bad",
        max_position_usd=-10.0,
        min_position_usd=-2.0,
        max_total_exposure_usd=-5.0,
        whale_scan_interval_cycles=0,
    )

    assert cfg.cli_timeout_seconds == 30
    assert cfg.cli_rate_limit_ms == 200
    assert cfg.cli_retry_count == 0
    assert cfg.cli_retry_backoff_seconds == 0.5
    assert cfg.order_fill_timeout_seconds == 30
    assert cfg.max_position_usd == 0.0
    assert cfg.max_total_exposure_usd >= cfg.max_position_usd
    assert cfg.min_position_usd == 0.0
    assert cfg.whale_scan_interval_cycles == 1
    assert Path(cfg.cli_binary).is_absolute()


def test_weather_vertical_builds_weather_search_universe():
    cfg = get_polymarket_cli_config(market_vertical="weather")

    assert cfg.market_vertical == "weather"
    assert cfg.search_symbols == ["WEATHER"]
    assert ("weather", "WEATHER") in cfg.crypto_search_queries
    assert any(query == "New York City weather" for query, _ in cfg.crypto_search_queries)
