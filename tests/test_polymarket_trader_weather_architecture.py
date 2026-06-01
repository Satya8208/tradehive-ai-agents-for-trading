import json
from datetime import datetime, timedelta

from src.agents.polymarket_trader.config import ExecutionMode, get_polymarket_cli_config
from src.agents.polymarket_trader.models import CLIMarket
from src.agents.polymarket_trader.station_mapper import WeatherStationMapper
from src.agents.polymarket_trader.weather_candidate_ranker import WeatherCandidateRanker
from src.agents.polymarket_trader.weather_contracts import FEATURE_SCHEMA_VERSION
from src.agents.polymarket_trader.weather_gate import WeatherGate
from src.agents.polymarket_trader.weather_signals import WeatherDataSignals


class _WeatherResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _ForecastSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return _WeatherResponse(
            {
                "timezone": "America/New_York",
                "hourly": {
                    "time": ["2026-05-03T00:00", "2026-05-03T12:00"],
                    "temperature_2m": [76.0, 82.0],
                    "precipitation": [0.0, 0.0],
                    "rain": [0.0, 0.0],
                    "snowfall": [0.0, 0.0],
                    "wind_speed_10m": [6.0, 8.0],
                    "wind_gusts_10m": [10.0, 14.0],
                },
            }
        )


def _market(question="Will NYC high temperature be above 75F on May 3?"):
    return CLIMarket(
        condition_id="weather-arch-1",
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


def test_station_mapper_resolves_known_city_to_station_contract():
    mapper = WeatherStationMapper()
    location = mapper.detect_location("Will NYC high temperature be above 75F?")

    target = mapper.resolve("weather-1", location, "NYC station market")

    assert target.status == "ok"
    assert target.resolution_station == "KNYC"
    assert target.metar_station == "KNYC"
    assert "station_manual_override" in target.quality_flags


def test_weather_signal_packet_includes_source_statuses_and_schema():
    cfg = get_polymarket_cli_config(market_vertical="weather", weather_forecast_days=3)
    signals = WeatherDataSignals(cfg, session=_ForecastSession())

    context = signals.get_context_for_market(_market())

    assert context["status"] == "ok"
    assert context["feature_schema_version"] == FEATURE_SCHEMA_VERSION
    assert context["source_statuses"]["station_mapper"] == "ok"
    assert context["source_statuses"]["open_meteo_forecast"] == "live_safe"
    assert context["station_mapping"]["resolution_station"] == "KNYC"
    assert context["forecast_snapshots"][0]["source_id"] == "open_meteo_forecast"
    assert context["station_bias"]["status"] == "missing_history"
    assert context["latency_signals"]["status"] == "first_scan_no_prior_price"
    assert context["run_lag_signals"]["status"] == "missing"
    assert {item["source_id"] for item in context["high_resolution_sources"]} == {"noaa_hrrr", "noaa_nbm"}
    assert context["high_resolution_sources"][0]["run_id"]
    assert "calibration_edge" in context["edge_reason_flags"]
    assert context["market_spec"]["question"] == "Will NYC high temperature be above 75F on May 3?"
    assert context["market_spec"]["resolution_station"] == "KNYC"
    assert "open_meteo_forecast" in context["evidence_refs"]["forecast_source_ids"]
    assert context["feature_packet"]["market_spec"]["yes_token_id"] == "yes"
    assert context["feature_packet"]["asof_time"]


def test_station_bias_catalog_adjusts_temperature_features(tmp_path):
    bias_path = tmp_path / "station_bias.json"
    bias_path.write_text(
        json.dumps(
            {
                "stations": {
                    "KNYC": {
                        "bias_correction_f": 2.5,
                        "sample_size": 80,
                        "source": "metar_urma_backtest",
                        "updated_at": "2026-05-01T00:00:00",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    cfg = get_polymarket_cli_config(
        market_vertical="weather",
        weather_forecast_days=3,
        weather_station_bias_path=str(bias_path),
    )
    signals = WeatherDataSignals(cfg, session=_ForecastSession())

    context = signals.get_context_for_market(_market())

    assert context["station_bias"]["status"] == "validated"
    assert context["forecast_metrics"]["high_temperature_f"] == 84.5
    assert context["raw_forecast_metrics"]["high_temperature_f"] == 82.0
    assert context["forecast_adjustments"]["high_temperature_f"]["delta"] == 2.5


def test_unknown_station_fails_closed_before_source_signal():
    cfg = get_polymarket_cli_config(market_vertical="weather", weather_forecast_days=3)
    signals = WeatherDataSignals(cfg, session=_ForecastSession())

    context = signals.get_context_for_market(_market("Will Atlantis high temperature be above 75F on May 3?"))

    assert context["status"] in {"unparsed_location", "unmapped_station"}
    if context["status"] == "unmapped_station":
        assert "unknown_station" in context["feature_blockers"]


def test_weather_gate_blocks_schema_mismatch_and_accepts_clean_packet(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        min_liquidity_usd=100.0,
        weather_min_probability_gap=0.08,
        _data_dir_override=tmp_path / "weather_gate",
    )
    market = _market()
    clean_context = {
        "status": "ok",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "weather_probability": 0.72,
        "weather_confidence": 0.75,
        "weather_edge_percent": 27.0,
        "recommended_side": "YES",
        "source_statuses": {"station_mapper": "ok", "open_meteo_forecast": "live_safe"},
    }
    candidate = WeatherCandidateRanker(cfg).build_candidate(market, clean_context)

    verdict = WeatherGate(cfg).evaluate(market, clean_context, candidate)
    assert verdict.accepted is True

    bad_context = dict(clean_context)
    bad_context["feature_schema_version"] = "old_schema"
    bad_candidate = WeatherCandidateRanker(cfg).build_candidate(market, bad_context)
    bad_verdict = WeatherGate(cfg).evaluate(market, bad_context, bad_candidate)

    assert bad_verdict.accepted is False
    assert bad_verdict.reason.startswith("weather_feature_schema_mismatch")
    assert bad_verdict.to_dict()["blocker_summary"]["by_category"]["schema_contract"] == 1
    assert bad_verdict.details["blocker_records"][0]["owner_role"] == "test_safety_engineer"


def test_weather_gate_can_require_high_resolution_confirmation(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        min_liquidity_usd=100.0,
        weather_min_probability_gap=0.08,
        weather_require_high_resolution_confirmation=True,
        _data_dir_override=tmp_path / "weather_gate",
    )
    market = _market()
    context = {
        "status": "ok",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "weather_probability": 0.72,
        "weather_confidence": 0.75,
        "weather_edge_percent": 27.0,
        "recommended_side": "YES",
        "source_statuses": {"station_mapper": "ok", "open_meteo_forecast": "live_safe"},
        "high_resolution_sources": [
            {"source_id": "noaa_hrrr", "status": "parser_required", "parser_required": True}
        ],
    }
    candidate = WeatherCandidateRanker(cfg).build_candidate(market, context)

    verdict = WeatherGate(cfg).evaluate(market, context, candidate)

    assert verdict.accepted is False
    assert "weather_high_resolution_parser_required:noaa_hrrr" in verdict.blockers

    accepted_context = dict(context)
    accepted_context["high_resolution_sources"] = [
        {
            "source_id": "noaa_hrrr",
            "status": "live_safe",
            "parser_required": False,
            "forecast_metrics": {"high_temperature_f": 82.0},
        }
    ]
    accepted_candidate = WeatherCandidateRanker(cfg).build_candidate(market, accepted_context)
    accepted_verdict = WeatherGate(cfg).evaluate(market, accepted_context, accepted_candidate)

    assert accepted_verdict.accepted is True


def test_weather_gate_never_unlocks_live_weather_without_manual_preflight(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.LIVE,
        market_vertical="weather",
        min_liquidity_usd=100.0,
        weather_min_probability_gap=0.08,
        weather_require_high_resolution_confirmation=True,
        weather_require_station_bias_validation=True,
        _data_dir_override=tmp_path / "weather_live_gate",
    )
    market = _market()
    context = {
        "status": "ok",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "weather_probability": 0.72,
        "weather_confidence": 0.75,
        "weather_edge_percent": 27.0,
        "recommended_side": "YES",
        "source_statuses": {"station_mapper": "ok", "open_meteo_forecast": "live_safe"},
        "station_bias": {"status": "validated", "sample_size": 100},
        "high_resolution_sources": [
            {
                "source_id": "noaa_hrrr",
                "status": "live_safe",
                "parser_required": False,
                "forecast_metrics": {"high_temperature_f": 82.0},
            }
        ],
    }
    candidate = WeatherCandidateRanker(cfg).build_candidate(market, context)

    verdict = WeatherGate(cfg).evaluate(market, context, candidate)

    assert verdict.accepted is False
    assert "weather_live_requires_preflight_and_manual_enablement" in verdict.blockers
