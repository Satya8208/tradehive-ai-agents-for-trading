from datetime import datetime, timedelta

from src.agents.polymarket_trader.config import ExecutionMode, get_polymarket_cli_config
from src.agents.polymarket_trader.models import CLIMarket
from src.agents.polymarket_trader.weather_ladder_consistency_alpha import (
    WeatherLadderConsistencyAlpha,
    WeatherLadderConsistencyAlphaScanner,
)
from src.agents.polymarket_trader.weather_market_tape import WeatherMarketTapeCollector
from src.agents.polymarket_trader.weather_orderbook_simulator import WeatherOrderbookFillSimulator


NOW = datetime(2026, 5, 8, 12, 0, 0)


def _market(
    question,
    market_id,
    yes_price=0.5,
    no_price=0.5,
    liquidity=5000.0,
    event_slug="nyc-weather-ladder",
):
    return CLIMarket(
        condition_id=market_id,
        question=question,
        symbol="WEATHER",
        yes_token_id=f"yes-{market_id}",
        no_token_id=f"no-{market_id}",
        yes_price=yes_price,
        no_price=no_price,
        liquidity=liquidity,
        volume_24h=500.0,
        end_date=NOW + timedelta(hours=8),
        event_slug=event_slug,
        slug=f"{event_slug}-{market_id}",
    )


class _BookCLI:
    def __init__(self, asks):
        self.asks = asks

    def get_order_book(self, token_id):
        ask = self.asks[token_id]
        bid = max(0.01, ask - 0.03)
        return {
            "bids": [{"price": f"{bid:.2f}", "size": "100"}],
            "asks": [
                {"price": f"{ask:.2f}", "size": "20"},
                {"price": f"{min(0.99, ask + 0.02):.2f}", "size": "20"},
            ],
        }


class _SizedBookCLI:
    def __init__(self, asks):
        self.asks = asks

    def get_order_book(self, token_id):
        ask, size = self.asks[token_id]
        bid = max(0.01, ask - 0.03)
        return {
            "bids": [{"price": f"{bid:.2f}", "size": "100"}],
            "asks": [{"price": f"{ask:.2f}", "size": f"{size:.4f}"}],
        }


class _Scanner:
    last_scan_telemetry = {"tradeable": 2}

    def __init__(self, markets):
        self.markets = markets

    def scan_markets(self, force_refresh=True):
        return self.markets


def test_orderbook_fill_simulator_consumes_depth_at_limit():
    market = _market("Will the high temperature in New York City exceed 70°F on May 8?", "low")
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        weather_market_tape_fetch_orderbook=True,
    )
    tape = WeatherMarketTapeCollector(cfg, _BookCLI({"yes-low": 0.40, "no-low": 0.62})).snapshot_market(
        market,
        fetch_orderbook=True,
    )

    fill = WeatherOrderbookFillSimulator(default_request_size_usd=5.0).simulate(
        tape,
        "YES",
        requested_size_usd=5.0,
        limit_price=0.40,
    )

    assert tape.yes_book["ask_levels"][0]["price"] == 0.40
    assert fill.status == "full"
    assert fill.average_price == 0.40
    assert fill.filled_notional_usd == 5.0


def test_ladder_consistency_finds_above_threshold_pair_edge():
    low = _market("Will the high temperature in New York City exceed 70°F on May 8?", "low")
    high = _market("Will the high temperature in New York City exceed 75°F on May 8?", "high")
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        weather_market_tape_fetch_orderbook=True,
    )
    tape = WeatherMarketTapeCollector(
        cfg,
        _BookCLI(
            {
                "yes-low": 0.40,
                "no-low": 0.62,
                "yes-high": 0.55,
                "no-high": 0.45,
            }
        ),
    ).snapshot_markets([low, high], fetch_orderbook=True)
    tape_by_market = {row.market_id: row for row in tape}

    candidates = WeatherLadderConsistencyAlpha(fee_rate=0.01, target_fill_usd=5.0).evaluate(
        [low, high],
        tape_by_market=tape_by_market,
        now=NOW,
    )

    accepted = [row for row in candidates if row.accepted_for_research]
    assert accepted
    assert accepted[0].alpha_type == "above_threshold_pair"
    assert accepted[0].edge_after_cost > 0.10
    assert "pays at least 1 share" in " ".join(accepted[0].proof)
    assert not accepted[0].blockers


def test_ladder_consistency_scales_atomic_capacity_for_partial_leg():
    low = _market("Will the high temperature in New York City exceed 70°F on May 8?", "low")
    high = _market("Will the high temperature in New York City exceed 75°F on May 8?", "high")
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        weather_market_tape_fetch_orderbook=True,
    )
    tape = WeatherMarketTapeCollector(
        cfg,
        _SizedBookCLI(
            {
                "yes-low": (0.40, 2.0),
                "no-low": (0.62, 20.0),
                "yes-high": (0.55, 20.0),
                "no-high": (0.45, 20.0),
            }
        ),
    ).snapshot_markets([low, high], fetch_orderbook=True)
    tape_by_market = {row.market_id: row for row in tape}

    candidates = WeatherLadderConsistencyAlpha(
        fee_rate=0.01,
        target_fill_usd=5.0,
        min_atomic_notional_usd=1.0,
    ).evaluate([low, high], tape_by_market=tape_by_market, now=NOW)

    accepted = [row for row in candidates if row.accepted_for_research]
    assert accepted
    assert accepted[0].max_atomic_qty == 2.0
    assert accepted[0].max_atomic_notional_usd == 1.7
    assert "atomic_basket_scaled_to_partial_fill" in accepted[0].quality_flags


def test_ladder_scanner_writes_accepted_and_rejected_proof_report(tmp_path):
    low = _market("Will the high temperature in New York City exceed 70°F on May 8?", "low")
    high = _market("Will the high temperature in New York City exceed 75°F on May 8?", "high")
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        weather_market_tape_fetch_orderbook=True,
        _data_dir_override=tmp_path / "pm_ladder",
    )
    scanner = WeatherLadderConsistencyAlphaScanner(
        config=cfg,
        scanner=_Scanner([low, high]),
        tape_collector=WeatherMarketTapeCollector(
            cfg,
            _BookCLI(
                {
                    "yes-low": 0.80,
                    "no-low": 0.25,
                    "yes-high": 0.45,
                    "no-high": 0.40,
                }
            ),
        ),
        output_dir=tmp_path / "ladder_report",
    )

    report = scanner.build_report(orderbook_limit=2)

    assert report["candidate_count"] == 0
    assert report["rejected_count"] == 1
    assert "ladder_edge_below_cost_buffer" in report["blocker_counts"]
    assert report["candidates"][0]["disproof"]
    assert scanner.latest_report_path.exists()
    assert scanner.latest_report_markdown_path.exists()


def test_ladder_scanner_fetches_complete_ladder_group_before_singletons(tmp_path):
    low = _market(
        "Will the high temperature in New York City exceed 70°F on May 8?",
        "low",
        liquidity=1000.0,
    )
    high = _market(
        "Will the high temperature in New York City exceed 75°F on May 8?",
        "high",
        liquidity=1000.0,
    )
    singleton = _market(
        "Will the high temperature in Chicago exceed 80°F on May 8?",
        "singleton",
        liquidity=50000.0,
        event_slug="chicago-weather-ladder",
    )
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        weather_market_tape_fetch_orderbook=True,
        _data_dir_override=tmp_path / "pm_ladder_complete_group",
    )
    scanner = WeatherLadderConsistencyAlphaScanner(
        config=cfg,
        scanner=_Scanner([singleton, low, high]),
        tape_collector=WeatherMarketTapeCollector(
            cfg,
            _BookCLI(
                {
                    "yes-low": 0.40,
                    "no-low": 0.62,
                    "yes-high": 0.55,
                    "no-high": 0.45,
                    "yes-singleton": 0.20,
                    "no-singleton": 0.82,
                }
            ),
        ),
        output_dir=tmp_path / "ladder_complete_group_report",
    )

    report = scanner.build_report(orderbook_limit=2)

    assert report["selected_ladder_groups"] == 1
    assert report["selected_ladder_markets"] == 2
    assert report["group_selection"]["eligible_groups"] == 1
    assert report["candidate_count"] == 1
    assert report["candidates"][0]["status"] == "candidate"


def test_ladder_grouping_does_not_merge_unknown_locations_by_metric_date():
    rows = [
        {
            "market": _market("Will the high temperature exceed 70°F on May 8?", "unknown-1"),
            "classification": {
                "market_id": "unknown-1",
                "station_id": "",
                "location_name": "",
                "metric": "temperature_high",
                "target_date": "2026-05-08",
                "event_slug": "unknown-location-70",
                "slug": "unknown-location-70",
            },
        },
        {
            "market": _market("Will the high temperature exceed 75°F on May 8?", "unknown-2"),
            "classification": {
                "market_id": "unknown-2",
                "station_id": "",
                "location_name": "",
                "metric": "temperature_high",
                "target_date": "2026-05-08",
                "event_slug": "unknown-location-75",
                "slug": "unknown-location-75",
            },
        },
    ]

    groups = WeatherLadderConsistencyAlpha._groups(rows)

    assert len(groups) == 2
