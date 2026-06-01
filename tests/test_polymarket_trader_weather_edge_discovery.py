import json

from src.agents.polymarket_trader.config import ExecutionMode, get_polymarket_cli_config
from src.agents.polymarket_trader.weather_contracts import FEATURE_SCHEMA_VERSION
from src.agents.polymarket_trader.weather_edge_discovery import WeatherEdgeDiscoveryBoard
from src.agents.polymarket_trader.weather_evidence_store import WeatherEvidenceStore


def _config(tmp_path):
    return get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        _data_dir_override=tmp_path / "pm_edge_discovery",
    )


def test_edge_discovery_identifies_candidate_supply_phase(tmp_path):
    cfg = _config(tmp_path)
    store = WeatherEvidenceStore(cfg)
    store.append_jsonl(
        store.market_tape_path,
        {
            "market_id": "weather-1",
            "captured_at": "2026-05-08T12:00:00",
            "executable_price_source": "orderbook_best_ask",
        },
    )
    store.append_jsonl(
        store.feature_snapshots_path,
        {
            "market_id": "weather-1",
            "status": "ok",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "selected_source_family": "open_meteo",
            "metric": "temperature_high",
            "threshold": 75.0,
            "raw_forecast_metrics": {"high_temperature_f": 83.0},
            "station_bias": {"status": "missing_history"},
            "latency_signals": {"status": "first_scan_no_prior_price"},
            "high_resolution_sources": [{"status": "not_applicable"}],
            "model_update_events": [{"event_type": "invalid_manifest", "actionable_for_research": False}],
        },
    )
    store.append_candidate_events(
        [
            {
                "market_id": "weather-1",
                "accepted": False,
                "reason": "weather_edge_below_research_gap",
                "final_trade_status": "blocked_by_weather_gate",
            }
        ],
        captured_at="2026-05-08T12:00:01",
    )
    store.write_replay_records(
        [
            {
                "market_id": "weather-1",
                "replay_status": "unresolved",
                "blockers": [
                    "weather_edge_below_research_gap",
                    "replay_gate_rejected",
                    "replay_label_pending",
                ],
                "accepted_by_gate": False,
            }
        ]
    )
    store.write_report(
        {
            "record_count": 1,
            "resolved_record_count": 0,
            "tradeable_replay_count": 0,
            "edge_status": "insufficient_evidence",
            "by_blocker": {"weather_edge_below_research_gap": 1, "replay_label_pending": 1},
            "by_final_trade_status": {"blocked_by_weather_gate": 1},
            "by_status": {"unresolved": 1},
            "deployment_verdict": {
                "accepted_for_paper_weather_trading": False,
                "remaining_requirements": ["need_at_least_50_resolved_replay_records"],
            },
        },
        "# evidence",
    )

    report = WeatherEdgeDiscoveryBoard(cfg, store=store).build_report(write=True)

    assert report["current_phase"] == "candidate_supply_needed"
    assert report["edge_built"] is False
    assert report["summary"]["source_family_counts"] == {"open_meteo": 1}
    statuses = {item["code"]: item["status"] for item in report["hypotheses"]}
    assert statuses["forecast_gap_candidate_supply"] == "needs_candidate_supply"
    assert statuses["station_bias"] == "needs_station_history"
    assert statuses["latency_behavioral_repricing"] == "needs_second_scan"
    assert "Keep weather live disabled" in " ".join(report["next_actions"])
    assert board_report_exists(store)


def test_edge_discovery_marks_paper_alpha_candidate_ready(tmp_path):
    cfg = _config(tmp_path)
    store = WeatherEvidenceStore(cfg)
    store.append_candidate_events(
        [
            {
                "market_id": "weather-accepted",
                "accepted": True,
                "reason": "ok",
                "final_trade_status": "executed",
            }
        ]
    )
    store.write_replay_records(
        [
            {
                "market_id": "weather-accepted",
                "replay_status": "resolved",
                "yes_resolved": True,
                "accepted_by_gate": True,
                "pnl_per_usd": 0.2,
                "blockers": [],
            }
        ]
    )
    store.write_report(
        {
            "record_count": 50,
            "resolved_record_count": 50,
            "tradeable_replay_count": 20,
            "edge_status": "accepted",
            "candidate_roi_per_1usd": 0.04,
            "by_blocker": {},
            "by_final_trade_status": {"executed": 20},
            "by_status": {"resolved": 50},
            "deployment_verdict": {"accepted_for_paper_weather_trading": True},
        },
        "# evidence",
    )

    report = WeatherEdgeDiscoveryBoard(cfg, store=store).build_report(write=False)

    assert report["current_phase"] == "paper_alpha_candidate_ready"
    assert report["edge_built"] is True
    assert report["live_weather_trading_allowed"] is False


def board_report_exists(store):
    report_path = store.root_dir / "latest_weather_edge_discovery_report.json"
    markdown_path = store.root_dir / "latest_weather_edge_discovery_report.md"
    assert report_path.exists()
    assert markdown_path.exists()
    saved = json.loads(report_path.read_text())
    assert saved["schema_version"] == "weather_edge_discovery_v1"
    return True
