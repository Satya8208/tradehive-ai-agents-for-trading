import json

import pytest

from src.agents.polymarket_trader.weather_contracts import WeatherResolutionTarget
from src.agents.polymarket_trader.weather_edge_features import WeatherStationBiasResolver
from src.agents.polymarket_trader.weather_station_bias_catalog import (
    WeatherStationBiasCatalogBuilder,
    WeatherStationBiasCatalogError,
)


def test_builds_catalog_from_json_and_resolver_can_consume_it(tmp_path):
    input_path = tmp_path / "residuals.json"
    output_path = tmp_path / "station_bias.json"
    input_path.write_text(
        json.dumps(
            {
                "observations": [
                    {
                        "station_id": "knyc",
                        "forecast_f": 80.0,
                        "observed_f": 82.0,
                        "observed_at": "2026-05-01T18:00:00",
                        "source": "metar_urma_join",
                        "lead_hours": 12,
                    },
                    {
                        "station_id": "KNYC",
                        "forecast_f": 81.0,
                        "observed_f": 84.0,
                        "observed_at": "2026-05-02T18:00:00",
                        "source": "metar_urma_join",
                        "lead_hours": 12,
                    },
                    {
                        "station": "KNYC",
                        "forecast_temperature_f": 79.0,
                        "observed_temperature_f": 80.0,
                        "observed_at": "2026-05-03T18:00:00",
                        "source": "metar_urma_join",
                        "forecast_hour": 24,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    payload = WeatherStationBiasCatalogBuilder(min_sample_size=3).write_catalog_from_file(
        input_path,
        output_path,
    )

    entry = payload["stations"]["KNYC"]
    assert output_path.exists()
    assert entry["status"] == "validated"
    assert entry["bias_correction_f"] == 2.0
    assert entry["sample_size"] == 3
    assert entry["source"] == "metar_urma_join"
    assert entry["updated_at"] == "2026-05-03T18:00:00"
    assert entry["metric_counts"] == {"temperature": 3}
    assert entry["lead_hour_counts"] == {"12": 2, "24": 1}

    snapshot = WeatherStationBiasResolver(output_path, min_sample_size=3).snapshot(
        WeatherResolutionTarget(
            market_id="weather-1",
            location_name="New York City",
            latitude=40.7128,
            longitude=-74.006,
            resolution_station="KNYC",
        )
    )
    assert snapshot.status == "validated"
    assert snapshot.correction_f == 2.0


def test_jsonl_residual_records_mark_limited_sample(tmp_path):
    input_path = tmp_path / "residuals.jsonl"
    input_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "station_id": "KMDW",
                        "residual_f": 1.0,
                        "observed_at": "2026-05-01T18:00:00",
                        "source": "metar_nbm_join",
                    }
                ),
                json.dumps(
                    {
                        "station_id": "KMDW",
                        "residual_f": 2.0,
                        "observed_at": "2026-05-02T18:00:00",
                        "source": "metar_nbm_join",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    payload = WeatherStationBiasCatalogBuilder(min_sample_size=3).build_catalog_from_file(input_path)

    entry = payload["stations"]["KMDW"]
    assert entry["status"] == "limited_sample"
    assert entry["bias_correction_f"] == 1.5
    assert entry["sample_size"] == 2
    assert "station_bias_sample_small" in entry["blockers"]


def test_csv_records_apply_quality_blocker_for_large_bias(tmp_path):
    input_path = tmp_path / "residuals.csv"
    input_path.write_text(
        "\n".join(
            [
                "station_id,forecast_f,observed_f,observed_at,source",
                "KLAX,70,78,2026-05-01T18:00:00,metar_city_join",
                "KLAX,71,80,2026-05-02T18:00:00,metar_city_join",
            ]
        ),
        encoding="utf-8",
    )

    payload = WeatherStationBiasCatalogBuilder(
        min_sample_size=2,
        max_abs_bias_f=5.0,
    ).build_catalog_from_file(input_path)

    entry = payload["stations"]["KLAX"]
    assert entry["sample_size"] == 2
    assert entry["bias_correction_f"] == 8.5
    assert entry["status"] == "quality_blocked"
    assert "station_bias_correction_large" in entry["blockers"]

    output_path = tmp_path / "quality_blocked_catalog.json"
    output_path.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = WeatherStationBiasResolver(output_path, min_sample_size=2).snapshot(
        WeatherResolutionTarget(
            market_id="weather-2",
            location_name="Los Angeles",
            latitude=34.0522,
            longitude=-118.2437,
            resolution_station="KLAX",
        )
    )
    assert snapshot.status == "quality_blocked"
    assert "station_bias_correction_large" in snapshot.blockers


def test_missing_input_fails_clearly(tmp_path):
    missing_path = tmp_path / "missing.jsonl"

    with pytest.raises(WeatherStationBiasCatalogError, match="not found"):
        WeatherStationBiasCatalogBuilder().build_catalog_from_file(missing_path)


def test_malformed_row_fails_clearly(tmp_path):
    input_path = tmp_path / "bad.json"
    input_path.write_text(
        json.dumps([{"station_id": "KNYC", "forecast_f": 80.0, "observed_at": "2026-05-01T18:00:00"}]),
        encoding="utf-8",
    )

    with pytest.raises(WeatherStationBiasCatalogError, match="forecast_f and observed_f"):
        WeatherStationBiasCatalogBuilder().build_catalog_from_file(input_path)
