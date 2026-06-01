from src.agents.polymarket_trader.weather_market_type_classifier import (
    CONTRACT_PRECIP_AMOUNT,
    CONTRACT_SPACE_WEATHER,
    CONTRACT_TEMP_HIGH,
    CONTRACT_TEMP_LOW,
    LANE_OBSERVATION_LAG,
    REGION_CONUS,
)
from src.agents.polymarket_trader.weather_market_universe_router import WeatherRoutedMarket
from src.agents.polymarket_trader.weather_observation_eligibility import (
    WEATHER_OBSERVATION_ELIGIBILITY_SCHEMA_VERSION,
    WeatherObservationEligibilityAuditor,
)


def _row(market_id="market-1", **classification_overrides):
    classification = {
        "contract_type": CONTRACT_TEMP_HIGH,
        "metric": "temperature_high",
        "operator": "above",
        "threshold": 85.0,
        "upper_threshold": None,
        "threshold_unit": "F",
        "target_date": "2026-05-08",
        "horizon_bucket": "already_in_window",
        "hours_to_end": 4.0,
        "station_id": "KNYC",
        "station_type": "ASOS",
        "region": REGION_CONUS,
        "source_applicability": ["METAR_ASOS_applicable", "NWS_applicable", "OpenMeteo_baseline"],
        "alpha_lanes": [LANE_OBSERVATION_LAG],
        "quality_flags": ["conus_station_mapped"],
        "blockers": [],
    }
    classification.update(classification_overrides)
    return WeatherRoutedMarket(
        market_id=market_id,
        question=f"Weather fixture {market_id}",
        classification=classification,
        microstructure={"liquidity": 1000.0, "depth_ok": True},
        research_score=99.0,
        route_reasons=["lane:observation_lag"],
    )


def test_observation_eligibility_accepts_temperature_high_low_and_precip_fixtures():
    auditor = WeatherObservationEligibilityAuditor()

    high = auditor.evaluate_routed(_row("high")).to_dict()
    low = auditor.evaluate_routed(
        _row(
            "low",
            contract_type=CONTRACT_TEMP_LOW,
            metric="temperature_low",
            operator="below",
            threshold=70.0,
        )
    ).to_dict()
    precip = auditor.evaluate_routed(
        _row(
            "precip",
            contract_type=CONTRACT_PRECIP_AMOUNT,
            metric="precipitation",
            threshold=0.25,
            threshold_unit="in",
        )
    ).to_dict()

    assert high["schema_version"] == WEATHER_OBSERVATION_ELIGIBILITY_SCHEMA_VERSION
    assert high["eligible"] is True
    assert low["eligible"] is True
    assert precip["eligible"] is True
    assert high["blockers"] == []
    assert "observation_pool_eligible" in high["quality_flags"]


def test_observation_eligibility_blocks_unsupported_market_before_pool():
    record = WeatherObservationEligibilityAuditor().evaluate_routed(
        _row(
            "space",
            contract_type=CONTRACT_SPACE_WEATHER,
            metric="space_weather",
            operator="",
            threshold=None,
            alpha_lanes=[],
        )
    ).to_dict()

    assert record["eligible"] is False
    assert "observation_lane_missing" in record["blockers"]
    assert "unsupported_market_type:space_weather" in record["blockers"]
    assert "unsupported_observation_metric:space_weather" in record["blockers"]
    assert record["blocker_summary"]["by_category"]["observation_eligibility"] >= 3


def test_observation_eligibility_blocks_ambiguous_station_context():
    record = WeatherObservationEligibilityAuditor().evaluate_routed(
        _row(
            "ambiguous",
            station_id="",
            station_type="",
            source_applicability=["OpenMeteo_only"],
            blockers=["ambiguous_station_mapping"],
        )
    ).to_dict()

    assert record["eligible"] is False
    assert "missing_station" in record["blockers"]
    assert "observation_context_blocked:ambiguous_station_mapping" in record["blockers"]


def test_observation_eligibility_blocks_future_and_closed_windows():
    auditor = WeatherObservationEligibilityAuditor()

    future = auditor.evaluate_routed(
        _row("future", horizon_bucket="gt_72h", hours_to_end=120.0)
    ).to_dict()
    closed = auditor.evaluate_routed(
        _row("closed", horizon_bucket="0_6h", hours_to_end=-0.1)
    ).to_dict()

    assert "future_window_not_observation_relevant:gt_72h" in future["blockers"]
    assert "closed_or_expired_window" in closed["blockers"]
    assert future["eligible"] is False
    assert closed["eligible"] is False


def test_observation_eligibility_audit_covers_every_routed_market():
    rows = [
        _row("eligible"),
        _row("missing-lane", alpha_lanes=[]),
        _row("missing-source", source_applicability=["OpenMeteo_only"]),
    ]

    audit = WeatherObservationEligibilityAuditor().audit_routed(rows)

    assert audit["schema_version"] == WEATHER_OBSERVATION_ELIGIBILITY_SCHEMA_VERSION
    assert audit["routed_market_count"] == 3
    assert audit["eligible_count"] == 1
    assert audit["ineligible_count"] == 2
    assert len(audit["records"]) == 3
    assert audit["eligible_market_ids"] == ["eligible"]
    assert audit["blocker_counts"]["observation_lane_missing"] == 1
    assert audit["blocker_counts"]["missing_observation_source"] == 1
