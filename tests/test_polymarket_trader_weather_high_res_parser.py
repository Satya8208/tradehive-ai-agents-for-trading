import json
from datetime import date, datetime

from src.agents.polymarket_trader.weather_contracts import WeatherResolutionTarget
from src.agents.polymarket_trader.weather_edge_features import WeatherHighResolutionSourceBuilder
from src.agents.polymarket_trader.weather_high_res_parser import WeatherHighResolutionParser


def _resolution():
    return WeatherResolutionTarget(
        market_id="weather-high-res-1",
        location_name="New York City",
        latitude=40.7128,
        longitude=-74.0060,
        resolution_station="KNYC",
        metar_station="KNYC",
        quality_flags=["station_manual_override"],
    )


def _point_payload(source_id="noaa_hrrr"):
    return {
        "source_id": source_id,
        "run_id": f"{source_id}:external:run",
        "latitude": 40.72,
        "longitude": -74.01,
        "grid_distance_km": 1.2,
        "forecast_metrics": {
            "high_temperature_f": 82.0,
            "low_temperature_f": 70.0,
            "precipitation_in": 0.01,
            "max_wind_mph": 12.0,
            "max_gust_mph": 20.0,
        },
    }


def test_parser_promotes_cached_point_json_to_live_safe_snapshot(tmp_path):
    source_dir = tmp_path / "noaa_hrrr"
    source_dir.mkdir()
    (source_dir / "latest.json").write_text(json.dumps(_point_payload()), encoding="utf-8")
    parser = WeatherHighResolutionParser(cache_dir=tmp_path)

    snapshot = parser.parse_manifest(
        {"source_id": "noaa_hrrr", "run_id": "noaa_hrrr:20260504:08:f010"},
        _resolution(),
    )

    assert snapshot.status == "live_safe"
    assert snapshot.parser == "point_json"
    assert snapshot.forecast_metrics["high_temperature_f"] == 82.0
    assert snapshot.grid_distance_km == 1.2
    assert not snapshot.blockers


def test_parser_can_disable_latest_fallback_for_historical_alpha(tmp_path):
    source_dir = tmp_path / "noaa_hrrr"
    source_dir.mkdir()
    (source_dir / "latest.json").write_text(json.dumps(_point_payload()), encoding="utf-8")
    parser = WeatherHighResolutionParser(cache_dir=tmp_path, allow_latest_fallback=False)

    snapshot = parser.parse_manifest(
        {"source_id": "noaa_hrrr", "run_id": "noaa_hrrr:20260504:08:f010"},
        _resolution(),
    )

    assert snapshot.status == "artifact_missing"
    assert snapshot.blockers == ["high_resolution_artifact_missing:noaa_hrrr"]


def test_parser_reports_missing_artifact_as_actionable_blocker(tmp_path):
    parser = WeatherHighResolutionParser(cache_dir=tmp_path)

    snapshot = parser.parse_manifest(
        {"source_id": "noaa_nbm", "run_id": "noaa_nbm:20260504:06:f012"},
        _resolution(),
    )

    assert snapshot.status == "artifact_missing"
    assert snapshot.blockers == ["high_resolution_artifact_missing:noaa_nbm"]


def test_builder_promotes_cached_hrrr_and_nbm_manifests(tmp_path):
    for source_id in ("noaa_hrrr", "noaa_nbm"):
        source_dir = tmp_path / source_id
        source_dir.mkdir()
        (source_dir / "latest.json").write_text(json.dumps(_point_payload(source_id)), encoding="utf-8")
    builder = WeatherHighResolutionSourceBuilder(cache_dir=tmp_path)

    manifests = builder.build_manifests(
        resolution=_resolution(),
        target_date=date(2026, 5, 4),
        metric="temperature_high",
        source_ids=["noaa_hrrr", "noaa_nbm"],
        generated_at=datetime(2026, 5, 4, 10, 0, 0),
    )

    assert {manifest["source_id"] for manifest in manifests} == {"noaa_hrrr", "noaa_nbm"}
    assert all(manifest["status"] == "live_safe" for manifest in manifests)
    assert all(manifest["parser_required"] is False for manifest in manifests)
    assert all(manifest["forecast_metrics"]["high_temperature_f"] == 82.0 for manifest in manifests)
    assert all(not manifest["blockers"] for manifest in manifests)
