from src.agents.polymarket_trader.weather_market_type_classifier import (
    CONTRACT_TEMP_HIGH,
    LANE_HRRR_NBM_RUN_SHOCK,
    LANE_OBSERVATION_LAG,
    LANE_STATION_SOURCE_MISMATCH,
    REGION_CONUS,
)
from src.agents.polymarket_trader.weather_market_universe_router import WeatherRoutedMarket
from src.agents.polymarket_trader.weather_observation_context import (
    WEATHER_OBSERVATION_CONTEXT_SCHEMA_VERSION,
    WeatherObservationContextCompiler,
)


def _row(market_id="ctx-1", **classification_overrides):
    classification = {
        "contract_type": CONTRACT_TEMP_HIGH,
        "metric": "temperature_high",
        "operator": "above",
        "threshold": 85.0,
        "target_date": "2026-05-08",
        "horizon_bucket": "0_6h",
        "hours_to_end": 4.0,
        "station_id": "KNYC",
        "station_type": "ASOS",
        "region": REGION_CONUS,
        "source_applicability": ["METAR_ASOS_applicable", "HRRR_applicable", "NBM_applicable"],
        "alpha_lanes": [LANE_OBSERVATION_LAG, LANE_HRRR_NBM_RUN_SHOCK],
        "blockers": [],
    }
    classification.update(classification_overrides)
    return WeatherRoutedMarket(
        market_id=market_id,
        question=f"Weather fixture {market_id}",
        classification=classification,
        microstructure={},
        research_score=1.0,
        route_reasons=[],
    )


def test_observation_context_routes_near_window_to_known_outcome():
    record = WeatherObservationContextCompiler().compile(_row()).to_dict()

    assert record["schema_version"] == WEATHER_OBSERVATION_CONTEXT_SCHEMA_VERSION
    assert record["routing_destination"] == "known_outcome_observation_lag"
    assert record["context_status"] == "ready"
    assert record["settlement_truth_status"] == "requires_polymarket_resolution_label_before_replay"
    assert record["official_observation_sources"] == ["METAR_ASOS_applicable"]


def test_observation_context_splits_future_market_to_forecast_lane():
    record = WeatherObservationContextCompiler().compile(
        _row(
            "future",
            alpha_lanes=[LANE_HRRR_NBM_RUN_SHOCK, LANE_STATION_SOURCE_MISMATCH],
            horizon_bucket="gt_72h",
            hours_to_end=120.0,
        )
    ).to_dict()

    assert record["routing_destination"] == "forecast_replay_lane"
    assert record["context_status"] == "future_window_routed_to_forecast"


def test_observation_context_audit_counts_repair_backlog():
    audit = WeatherObservationContextCompiler().audit_routed(
        [
            _row("ready"),
            _row("broken", station_id="", blockers=["unparsed_location"]),
        ]
    )

    assert audit["record_count"] == 2
    assert audit["destination_counts"]["known_outcome_observation_lag"] == 1
    assert audit["destination_counts"]["context_repair_backlog"] == 1
    assert audit["blocker_counts"]["observation_context_station_missing"] == 1
