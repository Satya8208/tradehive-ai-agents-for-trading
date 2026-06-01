from src.agents.polymarket_trader.config import ExecutionMode, get_polymarket_cli_config
from src.agents.polymarket_trader.weather_test_run import (
    WEATHER_TEST_RUN_SCHEMA_VERSION,
    WeatherSystemTestRunner,
)


class _KnownRunner:
    def run(self, candidate_limit=50, observation_hours=18):
        return {
            "markets_scanned": 10,
            "observation_eligible_count": 3,
            "evaluated_candidates": 2,
            "candidate_count": 1,
            "coverage_audit": {"verdict": "coverage_sufficient_for_next_replay_check"},
        }


class _ReplayEngine:
    def write_replay_and_report(self, min_resolved_markets=0, min_trade_decisions=0):
        return {
            "record_count": 1,
            "resolved_record_count": 0,
            "tradeable_replay_count": 0,
            "edge_status": "insufficient_evidence",
            "deployment_verdict": {
                "accepted_for_paper_weather_trading": False,
                "accepted_for_live_weather_trading": False,
                "blockers": ["need_at_least_1_resolved_replay_records"],
                "live_blockers": ["weather_live_requires_preflight_and_manual_enablement"],
            },
        }


class _LiveGate:
    def evaluate(self, evidence_report=None):
        return {
            "status": "hard_blocked",
            "eligible": False,
            "blockers": ["allow_live_weather_trading_false"],
        }


def test_weather_system_test_run_writes_operator_report(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        _data_dir_override=tmp_path / "pm_test_run",
    )
    report = WeatherSystemTestRunner(
        cfg,
        output_dir=tmp_path / "test_runs",
        known_outcome_runner=_KnownRunner(),
        replay_engine=_ReplayEngine(),
        live_gate=_LiveGate(),
    ).run(replay=True)

    assert report["schema_version"] == WEATHER_TEST_RUN_SCHEMA_VERSION
    assert report["status"] == "passed_research_test_live_blocked"
    assert report["phases"]["known_outcome_scan"]["status"] == "succeeded"
    assert report["phases"]["resolution_labels"]["status"] == "skipped"
    assert report["phases"]["replay_evidence"]["summary"]["edge_status"] == "insufficient_evidence"
    assert report["live_order_calls_allowed"] is False
    assert (tmp_path / "test_runs" / "latest_weather_test_run_report.json").exists()
