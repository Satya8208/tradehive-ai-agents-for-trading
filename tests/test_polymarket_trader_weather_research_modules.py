from src.agents.polymarket_trader.weather_behavior_monitor import WeatherBehaviorMonitor
from src.agents.polymarket_trader.weather_model_update_detector import WeatherModelUpdateDetector
from src.agents.polymarket_trader.weather_station_bias_catalog import (
    StationBiasObservation,
    WeatherStationBiasCatalogBuilder,
)
from src.agents.polymarket_trader.weather_structural_arb import (
    WeatherBucket,
    WeatherStructuralArbEngine,
)


def test_model_update_detector_marks_unrepriced_run_change_as_research_actionable():
    detector = WeatherModelUpdateDetector(max_source_age_minutes=180.0, repriced_move_threshold_points=2.0)
    first = detector.observe(
        {
            "source_id": "noaa_hrrr",
            "run_id": "noaa_hrrr:20260504:12:f006",
            "cycle_time": "2026-05-04T12:00:00",
            "source_age_minutes": 20.0,
            "status": "parser_required",
        },
        price_latency={"yes_price_change_points": None},
    )
    second = detector.observe(
        {
            "source_id": "noaa_hrrr",
            "run_id": "noaa_hrrr:20260504:13:f005",
            "cycle_time": "2026-05-04T13:00:00",
            "source_age_minutes": 12.0,
            "status": "parser_required",
        },
        price_latency={"yes_price_change_points": 0.5},
    )

    assert first.event_type == "first_seen"
    assert second.event_type == "run_changed"
    assert second.actionable_for_research is True


def test_station_bias_catalog_builds_validated_correction_from_observations():
    observations = [
        StationBiasObservation(
            station_id="KNYC",
            forecast_f=80.0 + index,
            observed_f=82.0 + index,
            observed_at=f"2026-05-{1 + index:02d}T18:00:00",
            source="metar_urma_join",
        )
        for index in range(3)
    ]

    catalog = WeatherStationBiasCatalogBuilder(min_sample_size=3).build_catalog(observations)
    entry = catalog["stations"]["KNYC"]

    assert entry["status"] == "validated"
    assert entry["bias_correction_f"] == 2.0
    assert entry["sample_size"] == 3


def test_behavior_monitor_flags_longshot_and_recency_candidates():
    signal = WeatherBehaviorMonitor(min_probability_gap=0.08).evaluate(
        {
            "yes_price": 0.08,
            "weather_probability": 0.24,
            "threshold": 80.0,
            "prior_observation_value": 83.0,
            "forecast_metrics": {"high_temperature_f": 77.0},
            "latency_signals": {"yes_price_change_points": -6.0},
        }
    )

    assert "longshot_underpricing_candidate" in signal["behavior_flags"]
    assert "behavior_monitor_research_only" in signal["quality_flags"]


def test_structural_arb_engine_detects_exhaustive_yes_basket_edge():
    buckets = [
        WeatherBucket("a", "70-75", 70.0, 75.0, yes_price=0.25, no_price=0.75, liquidity=100.0),
        WeatherBucket("b", "75-80", 75.0, 80.0, yes_price=0.28, no_price=0.72, liquidity=100.0),
        WeatherBucket("c", "80-85", 80.0, 85.0, yes_price=0.30, no_price=0.70, liquidity=100.0),
    ]

    candidates = WeatherStructuralArbEngine(fee_rate=0.01, min_edge_percent=1.0).detect(
        buckets,
        exhaustive=True,
    )

    assert any(candidate.arb_type == "weather_exhaustive_yes_basket" for candidate in candidates)
    yes_basket = next(candidate for candidate in candidates if candidate.arb_type == "weather_exhaustive_yes_basket")
    assert yes_basket.accepted_for_research is True
    assert yes_basket.edge_percent > 16.0
