from src.agents.polymarket_trader.weather_coverage_auditor import (
    WEATHER_COVERAGE_AUDIT_SCHEMA_VERSION,
    WeatherCoverageAuditor,
)


def test_weather_coverage_auditor_builds_known_outcome_funnel():
    report = {
        "markets_scanned": 1309,
        "routed_markets": 500,
        "observation_pool_candidates": 200,
        "observation_lane_candidates": 80,
        "evaluated_candidates": 80,
        "candidate_count": 1,
        "blocker_counts": {
            "executable_price_missing": 54,
            "executable_fill_below_minimum": 23,
            "threshold_not_known_from_observations": 32,
        },
    }

    audit = WeatherCoverageAuditor().audit_known_outcome(report)

    assert audit["schema_version"] == WEATHER_COVERAGE_AUDIT_SCHEMA_VERSION
    assert audit["lane"] == "known_outcome_observation_lag"
    assert audit["funnel"][0]["stage"] == "scan_to_router"
    assert audit["funnel"][1]["stage"] == "router_to_observation_eligible"
    assert audit["funnel"][-1]["stage"] == "evaluation_to_accepted_paper"
    assert audit["funnel"][-1]["input_count"] == 80
    assert audit["funnel"][-1]["output_count"] == 1
    assert audit["verdict"] == "paper_candidates_exist_but_depth_is_primary_bottleneck"
    assert audit["blocker_summary"]["by_category"]["execution_microstructure"] == 2
    assert "fillability subtype report" in audit["next_actions"][0]


def test_weather_coverage_auditor_names_observation_eligibility_root_cause():
    report = {
        "markets_scanned": 38,
        "routed_markets": 38,
        "observation_eligible_count": 0,
        "observation_pool_candidates": 0,
        "observation_lane_candidates": 0,
        "evaluated_candidates": 0,
        "candidate_count": 0,
        "blocker_counts": {},
        "observation_eligibility": {
            "eligible_count": 0,
            "blocker_counts": {
                "observation_lane_missing": 30,
                "future_window_not_observation_relevant:gt_72h": 8,
            },
        },
    }

    audit = WeatherCoverageAuditor().audit_known_outcome(report)

    assert audit["verdict"] == "observation_eligibility_blocked"
    assert audit["bottleneck_stage"]["stage"] == "router_to_observation_eligible"
    assert audit["top_blockers"][0] == {"blocker": "observation_lane_missing", "count": 30}
    assert "Repair router/classifier coverage" in audit["next_actions"][0]
