from src.agents.polymarket_trader.weather_blockers import (
    WEATHER_BLOCKER_SCHEMA_VERSION,
    blocker_summary,
    blockers_to_records,
    classify_weather_blocker,
)


def test_weather_blocker_taxonomy_classifies_core_weather_gate_failures():
    live = classify_weather_blocker("allow_live_weather_trading_false").to_dict()
    threshold = classify_weather_blocker("threshold_boundary_rounding_risk").to_dict()
    fill = classify_weather_blocker("executable_fill_below_minimum").to_dict()
    context = classify_weather_blocker("weather_context_unmapped_station").to_dict()
    observation = classify_weather_blocker("missing_observation_source").to_dict()

    assert live["schema_version"] == WEATHER_BLOCKER_SCHEMA_VERSION
    assert live["category"] == "live_safety"
    assert live["severity"] == "P0"
    assert live["owner_role"] == "release_gatekeeper"
    assert threshold["category"] == "threshold_state"
    assert threshold["owner_role"] == "contract_resolution_counsel"
    assert fill["category"] == "execution_microstructure"
    assert fill["route"] == "fillability_report"
    assert context["category"] == "market_spec"
    assert observation["category"] == "observation_eligibility"
    assert observation["route"] == "observation_pool_eligibility"


def test_weather_blocker_summary_preserves_order_and_counts_categories():
    records = blockers_to_records(
        [
            "weather_feature_schema_missing",
            "weather_feature_schema_missing",
            "weather_source_open_meteo_forecast_stale",
            "weather_ai_model_error:AuthenticationError",
        ]
    )
    summary = blocker_summary(record["raw"] for record in records)

    assert [record["code"] for record in records] == [
        "weather_feature_schema_missing",
        "weather_source_open_meteo_forecast_stale",
        "weather_ai_model_error",
    ]
    assert summary["by_category"]["schema_contract"] == 1
    assert summary["by_category"]["weather_source_freshness"] == 1
    assert summary["by_category"]["ai_decision"] == 1
