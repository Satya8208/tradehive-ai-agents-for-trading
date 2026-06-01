from src.agents.polymarket_trader.weather_agent_teams import (
    WEATHER_AGENT_TEAM_PLAN_SCHEMA_VERSION,
    WeatherAgentTeamPlanner,
)


def test_weather_agent_team_plan_turns_artifacts_into_review_queue():
    reports = {
        "known_outcome": {
            "generated_at": "2026-05-17T00:00:00",
            "schema_version": "weather_known_outcome_alpha_v1",
            "markets_scanned": 1309,
            "evaluated_candidates": 80,
            "candidate_count": 1,
            "blocker_counts": {
                "threshold_not_known_from_observations": 18,
                "executable_fill_below_minimum": 12,
            },
            "orderbook_fill_coverage": {
                "simulated_count": 42,
                "coverage_ratio": 0.52,
                "status_counts": {"no_depth": 22, "fillable": 20},
            },
        },
        "evidence": {
            "generated_at": "2026-05-17T00:05:00",
            "deployment_verdict": {
                "accepted_for_live_weather_trading": False,
            },
        },
        "research": {
            "generated_at": "2026-05-17T00:10:00",
            "run_lag_evidence": {"status": "ready"},
        },
        "ladder": {"candidate_count": 0, "blocker_counts": {"incomplete_group": 3}},
    }

    plan = WeatherAgentTeamPlanner().build(reports)

    assert plan["schema_version"] == WEATHER_AGENT_TEAM_PLAN_SCHEMA_VERSION
    assert plan["architecture_verdict"]["not_live_ready"] is True
    assert plan["pro_architecture_advice"]["status"] == "incorporated"
    assert plan["promotion_chain"] == [
        "AlphaLaneProposal",
        "AlphaExperimentPlan",
        "WeatherFeaturePacket",
        "AlphaEvidenceReport",
        "ReviewerFinding",
        "SystemReviewReport",
        "PaperGateDecision",
        "LiveEligibilityReport",
    ]
    patch_ids = {patch["id"] for patch in plan["pro_patch_sequence"]}
    assert "canonical_weather_feature_packet" in patch_ids
    assert "typed_blocker_taxonomy" in patch_ids
    assert "event_time_replay" in patch_ids
    patch_status = {patch["id"]: patch["status"] for patch in plan["pro_patch_sequence"]}
    assert patch_status["typed_blocker_taxonomy"] == "implemented"
    assert patch_status["coverage_auditor"] == "implemented"
    assert patch_status["fillability_subtype_report"] == "implemented_initial"
    assert patch_status["event_time_replay"] == "implemented_initial"

    strategy_roles = {role["role_id"] for role in plan["teams"]["strategy_edge_team"]}
    reviewer_roles = {role["role_id"] for role in plan["teams"]["reviewer_builder_team"]}
    assert "chief_weather_strategist" in strategy_roles
    assert "microstructure_alpha_lead" in strategy_roles
    assert "release_gatekeeper" in reviewer_roles
    assert "test_safety_engineer" in reviewer_roles

    lane_ids = {card["lane"] for card in plan["alpha_lane_cards"]}
    assert "official_observation_latency" in lane_ids
    assert "orderbook_depth_capacity" in lane_ids
    assert "model_update_lag" in lane_ids

    finding_ids = {finding["finding_id"] for finding in plan["current_review_findings"]}
    assert "live_weather_still_hard_blocked" in finding_ids
    assert "known_outcome_candidate_sample_not_promotable" in finding_ids
    assert "orderbook_depth_coverage_incomplete" in finding_ids
    assert "threshold_unknowns_need_disproof_dataset" in finding_ids
    assert "replay_not_live_accepted" in finding_ids

    assert plan["strategy_output_contract"]["schema_version"] == "weather_strategy_proposal_v1"
    assert plan["review_output_contract"]["schema_version"] == "weather_system_review_v1"
    queued_items = {item["work_item"] for item in plan["immediate_build_queue"]}
    assert "canonical_weather_feature_packet" not in queued_items
    assert "orderbook_depth_coverage_incomplete" in queued_items
    assert "event_time_replay" not in queued_items
