import json
from dataclasses import dataclass

from src.agents.polymarket_trader.weather_contracts import WeatherResolutionTarget
from src.agents.polymarket_trader.weather_high_res_ingestor import WeatherHighResolutionArtifactIngestor
from src.agents.polymarket_trader.weather_high_res_parser import WeatherHighResolutionParser


class _FakeResponse:
    content = b"grib-bytes"

    def raise_for_status(self):
        return None


class _FakeSession:
    def __init__(self):
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return _FakeResponse()


@dataclass
class _Completed:
    stdout: str
    stderr: str = ""
    returncode: int = 0


def _resolution():
    return WeatherResolutionTarget(
        market_id="weather-ingest-1",
        location_name="New York City",
        latitude=40.7128,
        longitude=-74.0060,
        resolution_station="KNYC",
        metar_station="KNYC",
    )


def _manifest(source_id="noaa_hrrr"):
    return {
        "source_id": source_id,
        "source_family": "noaa_high_resolution",
        "run_id": f"{source_id}:20260504:12:f006",
        "cycle_time": "2026-05-04T12:00:00",
        "target_reference_time": "2026-05-04T18:00:00",
        "target_lead_hours": 6,
        "forecast_hour": 6,
        "request_url": (
            "https://nomads.ncep.noaa.gov/cgi-bin/filter_hrrr_2d.pl"
            "?dir=/hrrr.20260504/conus&file=hrrr.t12z.wrfsfcf06.grib2"
            "&lev_2_m_above_ground=on&var_TMP=on&var_APCP=on&var_GUST=on"
        ),
    }


def _fake_runner(args, capture_output, text, timeout, check):
    return _Completed(
        stdout="\n".join(
            [
                "1:0:d=2026050412:TMP:2 m above ground:6 hour fcst:lon=285.99,lat=40.72,val=300.15",
                "2:0:d=2026050412:APCP:surface:0-6 hour acc fcst:lon=285.99,lat=40.72,val=1.0",
                "3:0:d=2026050412:GUST:surface:6 hour fcst:lon=285.99,lat=40.72,val=12.0",
            ]
        )
    )


def test_ingestor_writes_point_json_and_latest_cache(tmp_path):
    session = _FakeSession()
    ingestor = WeatherHighResolutionArtifactIngestor(
        tmp_path,
        session=session,
        wgrib2_binary="/bin/echo",
        command_runner=_fake_runner,
        min_request_interval_seconds=0,
    )

    result = ingestor.ingest_manifest(_manifest(), _resolution(), metric="temperature_high")

    assert result.status == "live_safe"
    assert result.forecast_metrics["high_temperature_f"] == 80.6
    assert result.forecast_metrics["precipitation_in"] == 0.0394
    assert result.forecast_metrics["max_gust_mph"] == 26.84
    assert session.urls
    assert "subregion=" in session.urls[0]
    assert "leftlon=-74.506" in session.urls[0]
    latest = tmp_path / "noaa_hrrr" / "latest.json"
    assert latest.exists()
    payload = json.loads(latest.read_text(encoding="utf-8"))
    assert payload["artifact_schema_version"] == "weather_high_res_point_v1"
    assert payload["grid_longitude"] == -74.01


def test_generated_point_json_is_consumed_by_existing_parser(tmp_path):
    ingestor = WeatherHighResolutionArtifactIngestor(
        tmp_path,
        session=_FakeSession(),
        wgrib2_binary="/bin/echo",
        command_runner=_fake_runner,
        min_request_interval_seconds=0,
    )
    ingestor.ingest_manifest(_manifest("noaa_nbm"), _resolution(), metric="temperature_high")

    snapshot = WeatherHighResolutionParser(cache_dir=tmp_path).parse_manifest(
        {"source_id": "noaa_nbm", "run_id": "noaa_nbm:20260504:12:f006"},
        _resolution(),
    )

    assert snapshot.status == "live_safe"
    assert snapshot.forecast_metrics["high_temperature_f"] == 80.6
    assert snapshot.parser == "point_json"


def test_ingestor_fails_closed_without_wgrib2_and_does_not_download(tmp_path):
    session = _FakeSession()
    ingestor = WeatherHighResolutionArtifactIngestor(
        tmp_path,
        session=session,
        wgrib2_binary="definitely_missing_wgrib2_binary",
        min_request_interval_seconds=0,
    )

    result = ingestor.ingest_manifest(_manifest(), _resolution())

    assert result.status == "parser_unavailable"
    assert result.blockers == ["wgrib2_missing"]
    assert session.urls == []


def test_ingestor_blocks_manifest_without_request_url(tmp_path):
    ingestor = WeatherHighResolutionArtifactIngestor(
        tmp_path,
        session=_FakeSession(),
        wgrib2_binary="/bin/echo",
        command_runner=_fake_runner,
        min_request_interval_seconds=0,
    )
    manifest = _manifest()
    manifest["request_url"] = ""

    result = ingestor.ingest_manifest(manifest, _resolution())

    assert result.status == "unavailable"
    assert result.blockers == ["high_resolution_request_url_missing:noaa_hrrr"]
