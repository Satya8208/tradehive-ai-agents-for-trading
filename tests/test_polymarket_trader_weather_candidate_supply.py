from datetime import datetime, timedelta

from src.agents.polymarket_trader.config import ExecutionMode, get_polymarket_cli_config
from src.agents.polymarket_trader.models import CLIMarket
from src.agents.polymarket_trader.weather_candidate_supply_report import WeatherCandidateSupplyReporter
from src.agents.polymarket_trader.weather_market_tape import WeatherMarketTapeCollector
from src.agents.polymarket_trader.weather_market_type_classifier import (
    LANE_HRRR_NBM_RUN_SHOCK,
    LANE_OBSERVATION_LAG,
    LANE_OPEN_METEO_CONTROL,
    LANE_STATION_SOURCE_MISMATCH,
    REGION_CONUS,
    REGION_NON_US,
    WeatherMarketTypeClassifier,
)
from src.agents.polymarket_trader.weather_market_universe_router import WeatherMarketUniverseRouter
from src.agents.polymarket_trader.weather_research_candidate_sampler import WeatherResearchCandidateSampler


def _market(question, market_id="m1", hours=4, liquidity=1000.0, yes=0.45, no=0.55):
    return CLIMarket(
        condition_id=market_id,
        question=question,
        symbol="WEATHER",
        yes_token_id=f"yes-{market_id}",
        no_token_id=f"no-{market_id}",
        yes_price=yes,
        no_price=no,
        liquidity=liquidity,
        volume_24h=100.0,
        end_date=datetime.utcnow() + timedelta(hours=hours),
        event_slug="weather-event",
        slug=f"weather-{market_id}",
    )


class _Scanner:
    last_scan_telemetry = {"tradeable": 3}

    def __init__(self, markets):
        self.markets = markets

    def scan_markets(self, force_refresh=True):
        return self.markets


class _BookCLI:
    def get_order_book(self, token_id):
        return {
            "bids": [{"price": "0.44", "size": "100"}],
            "asks": [{"price": "0.46", "size": "100"}],
        }


def test_weather_market_classifier_routes_conus_observation_and_hrrr_lanes():
    market = _market("Will the high temperature in New York City exceed 85°F on May 8?")

    classification = WeatherMarketTypeClassifier().classify(market)

    assert classification.contract_type == "temp_high_threshold"
    assert classification.region == REGION_CONUS
    assert classification.station_id == "KNYC"
    assert LANE_OBSERVATION_LAG in classification.alpha_lanes
    assert LANE_HRRR_NBM_RUN_SHOCK in classification.alpha_lanes
    assert LANE_STATION_SOURCE_MISMATCH in classification.alpha_lanes
    assert "station_bias_history_missing" not in classification.blockers


def test_weather_market_classifier_routes_non_conus_open_meteo_control():
    market = _market("Will the highest temperature in London be 15°C or below on May 9?")

    classification = WeatherMarketTypeClassifier().classify(market)

    assert classification.region == REGION_NON_US
    assert classification.station_id == "EGLL"
    assert "OpenMeteo_only" in classification.source_applicability
    assert LANE_OPEN_METEO_CONTROL in classification.alpha_lanes
    assert LANE_HRRR_NBM_RUN_SHOCK not in classification.alpha_lanes


def test_weather_router_and_sampler_build_stratified_research_supply():
    markets = [
        _market("Will the high temperature in New York City exceed 85°F on May 8?", "nyc"),
        _market("Will the high temperature in Chicago exceed 80°F on May 8?", "chi"),
        _market("Will the highest temperature in London be 15°C or below on May 9?", "lon", hours=36),
    ]
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        weather_market_tape_fetch_orderbook=True,
    )
    tape = WeatherMarketTapeCollector(cfg, _BookCLI()).snapshot_markets(markets, fetch_orderbook=True)
    tape_by_market = {row.market_id: row for row in tape}

    routed = WeatherMarketUniverseRouter().route_markets(markets, tape_by_market=tape_by_market)
    sample = WeatherResearchCandidateSampler(per_bucket=2, max_total=4).sample(routed)

    assert routed[0].research_score >= routed[-1].research_score
    assert sample.total_selected >= 2
    bucket_counts = {bucket.bucket_id: bucket.count for bucket in sample.buckets}
    assert bucket_counts["near_resolution_station"] == 2
    assert bucket_counts["open_meteo_controls"] == 1


def test_weather_candidate_supply_report_writes_universe_ledger(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        _data_dir_override=tmp_path / "pm_supply",
        weather_market_tape_fetch_orderbook=True,
    )
    markets = [
        _market("Will the high temperature in New York City exceed 85°F on May 8?", "nyc"),
        _market("Will the highest temperature in London be 15°C or below on May 9?", "lon", hours=36),
    ]
    reporter = WeatherCandidateSupplyReporter(
        config=cfg,
        scanner=_Scanner(markets),
        tape_collector=WeatherMarketTapeCollector(cfg, _BookCLI()),
        sampler=WeatherResearchCandidateSampler(per_bucket=5, max_total=10),
        output_dir=tmp_path / "supply_report",
    )

    report = reporter.build_report(fetch_orderbook=True, orderbook_limit=2)

    assert report["markets_scanned"] == 2
    assert report["research_candidate_count"] == 2
    assert report["orderbook_fetch_plan"]["selected_market_count"] == 2
    assert "P0_observation_lag_precheck" in report["orderbook_fetch_plan"]["selected_priority_counts"]
    assert report["sample_fill_coverage"]["sample_markets_with_full_yes_no_fill"] == 2
    assert reporter.latest_report_path.exists()
    assert reporter.latest_report_markdown_path.exists()
    ledger_lines = reporter.scan_universe_ledger_path.read_text().splitlines()
    assert len(ledger_lines) == 2
