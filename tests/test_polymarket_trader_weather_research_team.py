from datetime import datetime, timedelta
import json

from src.agents.polymarket_trader.config import ExecutionMode, get_polymarket_cli_config
from src.agents.polymarket_trader.models import CLIMarket
from src.agents.polymarket_trader.weather_research_team import WeatherResearchTeam


class _StubScanner:
    last_scan_telemetry = {"tradeable": 1}

    def __init__(self, market):
        self.market = market

    def scan_markets(self, force_refresh=True):
        return [self.market]

    def rank_markets(self, markets):
        return [(market, 1.0) for market in markets]


class _StubSignals:
    def __init__(self, market_id):
        self.market_id = market_id

    def get_market_context(self, markets):
        return {
            self.market_id: {
                "status": "ok",
                "location": "New York City",
                "metric": "temperature_high",
                "threshold": 75.0,
                "threshold_unit": "F",
                "weather_probability": 0.74,
                "weather_edge_percent": 29.0,
                "recommended_side": "YES",
                "weather_signal": "NYC forecast high 81F vs >=75F",
                "forecast_metrics": {"high_temperature_f": 81.0},
            }
        }


class _StubHighResCycleRunner:
    def __init__(self):
        self.calls = []

    def run(self, markets, dry_run=False, force=False):
        self.calls.append((list(markets), dry_run, force))

        class _Report:
            def summary(self):
                return {
                    "status": "live_safe_cache_ready",
                    "total_markets": len(markets),
                    "ingested_count": 1,
                    "blocked_count": 0,
                    "dry_run": dry_run,
                }

        return _Report()


def test_weather_research_team_writes_ranked_report(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        search_symbols=["WEATHER"],
        _data_dir_override=tmp_path / "weather_data",
        weather_min_probability_gap=0.08,
    )
    market = CLIMarket(
        condition_id="weather-research-1",
        question="Will NYC high temperature be above 75F on May 3?",
        symbol="WEATHER",
        yes_token_id="801",
        no_token_id="802",
        yes_price=0.45,
        no_price=0.55,
        liquidity=2000.0,
        volume_24h=100.0,
        end_date=datetime.utcnow() + timedelta(hours=8),
        market_type="bullish",
        price_target=75.0,
        slug="nyc-temperature",
    )
    output_dir = tmp_path / "report"
    team = WeatherResearchTeam(
        config=cfg,
        scanner=_StubScanner(market),
        signals=_StubSignals(market.condition_id),
        output_dir=output_dir,
    )

    report = team.build_report(force_refresh=True, limit=1)

    assert report["candidate_count"] == 1
    assert report["candidates"][0]["recommended_side"] == "YES"
    assert report["team_manifest"]["objective"].startswith("Create edge in Polymarket weather markets")
    role_ids = {role["role_id"] for role in report["team_manifest"]["roles"]}
    assert "forecast_modeling_lead" in role_ids
    assert "microstructure_execution_lead" in role_ids
    assert "weather_data_engineer" in role_ids
    assert "quantitative_meteorologist" in role_ids
    source_ids = {source["source_id"] for source in report["data_source_backlog"]}
    assert "polymarket_clob_orderbook" in source_ids
    assert "ncep_nomads" in source_ids
    assert "noaa_awc_metar" in source_ids
    track_codes = {track["code"] for track in report["edge_generation_plan"]["tracks"]}
    assert "structural_bucket_arbitrage" in track_codes
    assert "asof_calibrated_model" in track_codes
    experiment_codes = {experiment["code"] for experiment in report["experiment_backlog"]}
    assert "leakage_audit" in experiment_codes
    assert "execution_cost_model" in experiment_codes
    roadmap_lanes = {item["lane"] for item in report["ranked_edge_roadmap"]}
    assert "model_update_lag" in roadmap_lanes
    assert "station_bias" in roadmap_lanes
    workstream_lanes = {
        item["lane"] for item in report["research_team_operating_model"]["workstreams"]
    }
    assert "behavioral_mispricing" in workstream_lanes
    assert "structural_bucket_arbitrage" in workstream_lanes
    assert report["deployment_verdict"]["current_scope"] == "research_only"
    assert report["deployment_verdict"]["strict_promotion_bar"]["min_resolved_records"] == 300
    assert report["agent_team_plan"]["schema_version"] == "weather_agent_team_plan_v1"
    assert report["agent_team_plan"]["pro_architecture_advice"]["status"] == "incorporated"
    assert "WeatherFeaturePacket" in report["agent_team_plan"]["promotion_chain"]
    strategy_roles = {
        role["role_id"] for role in report["agent_team_plan"]["teams"]["strategy_edge_team"]
    }
    reviewer_roles = {
        role["role_id"] for role in report["agent_team_plan"]["teams"]["reviewer_builder_team"]
    }
    assert "chief_weather_strategist" in strategy_roles
    assert "release_gatekeeper" in reviewer_roles
    json_path = output_dir / "latest_weather_edge_report.json"
    md_path = output_dir / "latest_weather_edge_report.md"
    assert json_path.exists()
    assert md_path.exists()
    saved = json.loads(json_path.read_text())
    assert saved["market_vertical"] == "weather"
    assert saved["agent_team_plan"]["review_output_contract"]["schema_version"] == "weather_system_review_v1"
    markdown = md_path.read_text()
    assert "NYC forecast high 81F" in markdown
    assert "## How Edge Gets Created" in markdown
    assert "## Agent Team Operating Plan" in markdown
    assert "## Reviewer Builder Team" in markdown
    assert "canonical_weather_feature_packet" in markdown
    assert "## Research Agent Team" in markdown
    assert "## Ranked Edge Roadmap" in markdown
    assert "weather_model_update_detector.py" in markdown
    assert "Strict promotion bar" in markdown


def test_weather_research_team_refreshes_high_res_before_context_when_enabled(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        search_symbols=["WEATHER"],
        weather_auto_ingest_high_resolution=True,
        _data_dir_override=tmp_path / "weather_data",
    )
    market = CLIMarket(
        condition_id="weather-research-high-res-1",
        question="Will NYC high temperature be above 75F on May 3?",
        symbol="WEATHER",
        yes_token_id="801",
        no_token_id="802",
        yes_price=0.45,
        no_price=0.55,
        liquidity=2000.0,
        volume_24h=100.0,
        end_date=datetime.utcnow() + timedelta(hours=8),
    )
    runner = _StubHighResCycleRunner()
    output_dir = tmp_path / "report"
    state_dir = cfg.data_dir / "weather_run_lag"
    state_dir.mkdir(parents=True)
    (state_dir / "latest_weather_run_lag_state.json").write_text(
        json.dumps(
            {
                "updated_at": "2026-05-04T13:05:00",
                "event_log_path": str(state_dir / "weather_run_lag_events.jsonl"),
                "latest_by_key": {
                    "noaa_hrrr|KNYC|temperature_high": {
                        "run_id": "noaa_hrrr:20260504:13:f005"
                    }
                },
                "last_event": {
                    "event_type": "new_run_arrival",
                    "run_id": "noaa_hrrr:20260504:13:f005",
                },
            }
        ),
        encoding="utf-8",
    )
    team = WeatherResearchTeam(
        config=cfg,
        scanner=_StubScanner(market),
        signals=_StubSignals(market.condition_id),
        high_res_cycle_runner=runner,
        output_dir=output_dir,
    )

    report = team.build_report(force_refresh=True, limit=1)

    assert runner.calls
    assert runner.calls[0][0][0].condition_id == market.condition_id
    assert report["high_resolution_ingest"]["status"] == "live_safe_cache_ready"
    assert report["run_lag_evidence"]["status"] == "ready"
    assert report["run_lag_evidence"]["tracked_source_station_metrics"] == 1
    markdown = (output_dir / "latest_weather_edge_report.md").read_text()
    assert "High-resolution ingest: `live_safe_cache_ready`" in markdown
    assert "Run-lag evidence: `ready`" in markdown
