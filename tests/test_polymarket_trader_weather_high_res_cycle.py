from datetime import datetime

from src.agents.polymarket_trader.config import get_polymarket_cli_config
from src.agents.polymarket_trader.models import CLIMarket
from src.agents.polymarket_trader.weather_high_res_cycle import WeatherHighResolutionIngestCycleRunner
from src.agents.polymarket_trader.weather_high_res_ingestor import WeatherHighResolutionIngestResult


class _FakeIngestor:
    def __init__(self):
        self.calls = []

    def ingest_manifest(self, manifest, resolution, metric="", force=False):
        self.calls.append(
            {
                "manifest": manifest,
                "resolution": resolution,
                "metric": metric,
                "force": force,
            }
        )
        return WeatherHighResolutionIngestResult(
            source_id=manifest["source_id"],
            status="live_safe",
            run_id=manifest["run_id"],
            point_artifact_path=f"/tmp/{manifest['source_id']}.json",
            latest_artifact_path=f"/tmp/{manifest['source_id']}/latest.json",
            request_url=manifest["request_url"],
            parser="fake_point_parser",
            forecast_metrics={"high_temperature_f": 81.0},
            quality_flags=["fake_high_resolution_ingest"],
        )


def _market(question="Will NYC high temperature be above 75F on May 3?"):
    return CLIMarket(
        condition_id="weather-cycle-1",
        question=question,
        symbol="WEATHER",
        yes_token_id="yes",
        no_token_id="no",
        yes_price=0.45,
        no_price=0.55,
        liquidity=1000.0,
        volume_24h=100.0,
        end_date=datetime(2026, 5, 3, 23, 59),
    )


def test_high_res_cycle_ingests_market_manifests_and_writes_report(tmp_path):
    cfg = get_polymarket_cli_config(
        market_vertical="weather",
        weather_high_resolution_sources=["noaa_hrrr"],
        _data_dir_override=tmp_path / "pm_weather",
    )
    fake_ingestor = _FakeIngestor()
    runner = WeatherHighResolutionIngestCycleRunner(cfg, ingestor=fake_ingestor)

    report = runner.run([_market()])

    assert report.status == "live_safe_cache_ready"
    assert report.ingested_count == 1
    assert report.blocked_count == 0
    assert report.report_path
    assert report.ledger_path
    assert fake_ingestor.calls[0]["metric"] == "temperature_high"
    assert fake_ingestor.calls[0]["resolution"].resolution_station == "KNYC"
    assert report.items[0].forecast_metrics["high_temperature_f"] == 81.0
    assert report.run_lag_event_count == 1
    assert report.items[0].run_lag_event["event_type"] == "first_seen"
    assert report.items[0].run_lag_event["station"] == "KNYC"
    assert report.items[0].run_lag_event["metric"] == "temperature_high"
    assert report.items[0].run_lag_event["clob_price_snapshot"]["yes_price"] == 0.45


def test_high_res_cycle_dry_run_plans_without_ingesting(tmp_path):
    cfg = get_polymarket_cli_config(
        market_vertical="weather",
        weather_high_resolution_sources=["noaa_hrrr", "noaa_nbm"],
        _data_dir_override=tmp_path / "pm_weather",
    )
    fake_ingestor = _FakeIngestor()
    runner = WeatherHighResolutionIngestCycleRunner(cfg, ingestor=fake_ingestor)

    report = runner.run([_market()], dry_run=True)

    assert report.status == "planned"
    assert report.planned_count == 2
    assert report.ingested_count == 0
    assert report.run_lag_event_count == 0
    assert fake_ingestor.calls == []
    assert {item.source_id for item in report.items} == {"noaa_hrrr", "noaa_nbm"}


def test_high_res_cycle_fails_closed_for_unmapped_market(tmp_path):
    cfg = get_polymarket_cli_config(
        market_vertical="weather",
        _data_dir_override=tmp_path / "pm_weather",
    )
    fake_ingestor = _FakeIngestor()
    runner = WeatherHighResolutionIngestCycleRunner(cfg, ingestor=fake_ingestor)

    report = runner.run([_market("Will Atlantis high temperature be above 75F on May 3?")])

    assert report.status == "blocked"
    assert report.skipped_count == 1
    assert report.items[0].blockers == ["unparsed_location"]
    assert fake_ingestor.calls == []
