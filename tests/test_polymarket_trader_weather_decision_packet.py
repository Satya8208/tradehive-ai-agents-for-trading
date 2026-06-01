from src.agents.polymarket_trader.weather_candidate_lifecycle import WeatherCandidateLifecycleBuilder
from src.agents.polymarket_trader.weather_decision_packet import (
    WEATHER_DECISION_PACKET_SCHEMA_VERSION,
    WeatherDecisionPacketBuilder,
)


def test_weather_decision_packet_records_replayable_known_outcome_candidate():
    candidate = {
        "market_id": "m1",
        "alpha_code": "OBSERVATION_LAG_STATION_THRESHOLD_V1",
        "status": "candidate",
        "side": "YES",
        "p_yes": 0.985,
        "selected_win_probability": 0.985,
        "p_yes_source": "official_observation_fact",
        "probability_role": "settlement_fact",
        "executable_price": 0.46,
        "executable_price_source": "orderbook_depth_simulation",
        "edge_after_cost": 0.505,
        "fill_simulation": {
            "status": "full",
            "requested_size_usd": 5.0,
            "filled_notional_usd": 5.0,
            "average_price": 0.46,
            "price_source": "orderbook_depth_simulation",
        },
        "classification": {
            "metric": "temperature_high",
            "operator": "above",
            "threshold": 85.0,
            "target_date": "2026-05-08",
            "station_id": "KNYC",
            "alpha_lanes": ["observation_lag_station_threshold"],
        },
        "threshold_state": {"status": "known_or_near_known"},
        "station_state": {"station_id": "KNYC"},
        "blockers": [],
        "quality_flags": ["known_outcome_alpha_research_only"],
    }
    tape = {
        "market_id": "m1",
        "captured_at": "2026-05-08T10:00:00",
        "yes_book": {"ask_levels": [{"price": 0.46, "size": 20.0}]},
    }

    builder = WeatherDecisionPacketBuilder()
    packets = builder.build_known_outcome_packets(
        [candidate],
        tape_by_market={"m1": tape},
        run_id="run-1",
        decision_time="2026-05-08T10:00:02",
    )
    events = builder.to_candidate_events(packets, captured_at="2026-05-08T10:00:02")
    feature_context = builder.feature_context_for_packet(packets[0], candidate, tape)

    assert packets[0]["schema_version"] == WEATHER_DECISION_PACKET_SCHEMA_VERSION
    assert packets[0]["status"] == "current_scan_candidate"
    assert packets[0]["packet_hash"]
    assert packets[0]["evidence_refs"]["threshold_state_ref"]
    assert events[0]["final_trade_status"] == "planned"
    assert events[0]["candidate"]["model_probability"] == 0.985
    assert feature_context["feature_schema_version"] == "weather_feature_packet_v1"
    assert feature_context["station_mapping"]["resolution_station"] == "KNYC"


def test_weather_candidate_lifecycle_starts_pending_until_outcome_join():
    packet = {
        "decision_id": "wdp_1",
        "run_id": "run-1",
        "market_id": "m1",
        "lane_id": "OBSERVATION_LAG_STATION_THRESHOLD_V1",
        "decision_asof_time": "2026-05-08T10:00:02",
        "status": "current_scan_candidate",
        "side": "YES",
        "expected_edge_after_cost": 0.5,
        "simulated_fill_size_usd": 5.0,
        "simulated_entry_price": 0.46,
        "blockers": [],
        "evidence_refs": {"decision_packet_ref": "weather_decision_packet:wdp_1"},
    }

    records = WeatherCandidateLifecycleBuilder().build_from_decision_packets(
        [packet],
        discovered_at="2026-05-08T10:00:02",
    )
    summary = WeatherCandidateLifecycleBuilder.summarize(records, records_written=1)

    assert records[0]["status"] == "pending_resolution"
    assert records[0]["blockers"] == ["candidate_pending_resolution"]
    assert summary["lifecycle_records_written"] == 1
    assert summary["by_status"] == {"pending_resolution": 1}
