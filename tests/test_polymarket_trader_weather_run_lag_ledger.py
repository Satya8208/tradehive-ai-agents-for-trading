import json
from datetime import datetime

from src.agents.polymarket_trader.weather_run_lag_ledger import WeatherRunLagLedger


def _manifest(run_id="noaa_hrrr:20260504:12:f006", temp=81.0):
    return {
        "source_id": "noaa_hrrr",
        "source_family": "noaa_high_resolution",
        "run_id": run_id,
        "cycle_time": "2026-05-04T12:00:00",
        "target_reference_time": "2026-05-04T18:00:00",
        "forecast_hour": 6,
        "resolution_station": "KNYC",
        "metric": "temperature_high",
        "request_url": "https://nomads.example/hrrr",
        "forecast_metrics": {
            "high_temperature_f": temp,
            "precipitation_in": 0.04,
        },
    }


def test_run_lag_ledger_records_first_run_and_latest_state(tmp_path):
    ledger = WeatherRunLagLedger(tmp_path, repriced_move_threshold_points=2.0)

    event = ledger.observe(
        _manifest(),
        clob_snapshot={"market_id": "weather-nyc", "yes_price": 0.42, "no_price": 0.58},
        observed_at=datetime(2026, 5, 4, 12, 15),
    )

    assert event["event_type"] == "first_seen"
    assert event["status"] == "recorded"
    assert event["state_key"] == "noaa_hrrr|KNYC|temperature_high"
    assert event["run_lag_minutes"] == 15.0
    assert event["forecast_delta"] == {}
    assert event["clob_price_snapshot"]["yes_price"] == 0.42
    assert event["model_update_detector_input"]["source_id"] == "noaa_hrrr"

    events_path = tmp_path / "weather_run_lag_events.jsonl"
    state_path = tmp_path / "latest_weather_run_lag_state.json"
    assert events_path.exists()
    assert state_path.exists()
    assert len(events_path.read_text(encoding="utf-8").splitlines()) == 1
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["latest_by_key"]["noaa_hrrr|KNYC|temperature_high"]["run_id"] == "noaa_hrrr:20260504:12:f006"


def test_run_lag_ledger_detects_new_run_delta_and_clob_repricing(tmp_path):
    ledger = WeatherRunLagLedger(tmp_path, repriced_move_threshold_points=2.0)
    ledger.observe(
        _manifest(temp=81.0),
        clob_snapshot={"yes_price": 0.42, "no_price": 0.58},
        observed_at="2026-05-04T12:10:00",
    )

    event = ledger.observe(
        _manifest(run_id="noaa_hrrr:20260504:13:f005", temp=84.5),
        clob_snapshot={"yes_price": 0.455, "no_price": 0.545},
        observed_at="2026-05-04T13:05:00",
    )

    assert event["event_type"] == "new_run_arrival"
    assert event["previous_run_id"] == "noaa_hrrr:20260504:12:f006"
    assert event["forecast_delta"]["high_temperature_f"] == {
        "previous": 81.0,
        "current": 84.5,
        "delta": 3.5,
    }
    assert event["price_movement"]["yes_price_change_points"] == 3.5
    assert event["price_movement"]["no_price_change_points"] == -3.5
    assert event["price_move_points"] == 3.5
    assert event["market_repriced"] is True
    assert event["actionable_for_research"] is False
    assert event["price_latency_for_detector"] == {
        "yes_price_change_points": 3.5,
        "no_price_change_points": -3.5,
    }


def test_run_lag_ledger_loads_prior_state_across_instances(tmp_path):
    first_ledger = WeatherRunLagLedger(tmp_path)
    first_ledger.observe(
        _manifest(temp=78.0),
        clob_snapshot={"yes_price": 0.31, "no_price": 0.69},
        observed_at="2026-05-04T12:03:00",
    )

    second_ledger = WeatherRunLagLedger(tmp_path)
    event = second_ledger.observe(
        _manifest(run_id="noaa_hrrr:20260504:13:f005", temp=79.25),
        clob_snapshot={"yes_price": 0.315, "no_price": 0.685},
        observed_at="2026-05-04T13:03:00",
    )

    assert event["previous_run_id"] == "noaa_hrrr:20260504:12:f006"
    assert event["forecast_delta"]["high_temperature_f"]["delta"] == 1.25
    assert event["market_repriced"] is False
    assert event["actionable_for_research"] is True


def test_run_lag_ledger_fails_closed_for_missing_required_identity(tmp_path):
    ledger = WeatherRunLagLedger(tmp_path)
    manifest = _manifest()
    manifest.pop("run_id")
    manifest.pop("resolution_station")

    event = ledger.observe(manifest, observed_at="2026-05-04T12:10:00")

    assert event["event_type"] == "invalid_manifest"
    assert event["status"] == "fail_closed"
    assert event["state_key"] == ""
    assert event["blockers"] == ["run_id_missing", "station_missing"]
    assert "weather_run_lag_fail_closed" in event["quality_flags"]

    state = json.loads((tmp_path / "latest_weather_run_lag_state.json").read_text(encoding="utf-8"))
    assert state["latest_by_key"] == {}
    assert state["last_fail_closed_event"]["blockers"] == ["run_id_missing", "station_missing"]
    assert len((tmp_path / "weather_run_lag_events.jsonl").read_text(encoding="utf-8").splitlines()) == 1
