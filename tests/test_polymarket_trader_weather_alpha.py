from datetime import date, datetime

from src.agents.polymarket_trader.config import get_polymarket_cli_config
from src.agents.polymarket_trader.models import CLIMarket
from src.agents.polymarket_trader.weather_alpha import WeatherAlphaBacktester
from src.agents.polymarket_trader.weather_alpha_model import WeatherAlphaCalibrationEvaluator
from src.agents.polymarket_trader.weather_price_history import select_price_at_or_before
from src.agents.polymarket_trader.weather_signals import WeatherLocation, WeatherMarketParse


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAlphaSession:
    def post(self, url, json=None, timeout=None):
        if "clob.polymarket.com/batch-prices-history" in url:
            return _FakeResponse(
                {"history": {token_id: [{"t": json["start_ts"] + 3600, "p": 0.04}] for token_id in json["markets"]}}
            )
        raise AssertionError(f"unexpected POST URL {url}")

    def get(self, url, params=None, timeout=None):
        if "gamma-api.polymarket.com/events" in url:
            return _FakeResponse(
                [
                    {
                        "slug": "highest-temperature-in-tokyo-on-may-2",
                        "title": "Highest temperature in Tokyo on May 2?",
                        "description": "Resolves by official weather reporting.",
                        "endDate": "2026-05-02T12:00:00Z",
                        "markets": [
                            {
                                "id": "weather-alpha-1",
                                "conditionId": "0xweatheralpha1",
                                "question": "Will the highest temperature in Tokyo be 16C on May 2?",
                                "slug": "highest-temperature-in-tokyo-on-may-2-16c",
                                "description": "Resolves by official weather reporting.",
                                "endDate": "2026-05-02T12:00:00Z",
                                "outcomes": "[\"Yes\", \"No\"]",
                                "outcomePrices": "[\"1\", \"0\"]",
                                "clobTokenIds": "[\"1001\", \"1002\"]",
                                "volumeNum": 1000,
                                "liquidityNum": 1000,
                                "active": True,
                                "closed": True,
                            }
                        ],
                    }
                ]
            )
        if "geocoding-api.open-meteo.com" in url:
            return _FakeResponse(
                {"results": [{"name": "Tokyo", "latitude": 35.6762, "longitude": 139.6503}]}
            )
        if "clob.polymarket.com/prices-history" in url:
            return _FakeResponse({"history": [{"t": params["startTs"] + 3600, "p": 0.04}]})
        if "previous-runs-api.open-meteo.com" in url:
            return _FakeResponse(
                {
                    "timezone": "Asia/Tokyo",
                    "hourly": {
                        "time": [
                            "2026-05-02T00:00",
                            "2026-05-02T01:00",
                            "2026-05-02T02:00",
                        ],
                        "temperature_2m": [60.0, 59.0, 58.0],
                        "temperature_2m_previous_day1": [60.0, 59.0, 58.0],
                    },
                }
            )
        if "historical-forecast-api.open-meteo.com" in url:
            return _FakeResponse(
                {
                    "timezone": "Asia/Tokyo",
                    "hourly": {
                        "time": [
                            "2026-05-02T00:00",
                            "2026-05-02T01:00",
                            "2026-05-02T02:00",
                        ],
                        "temperature_2m": [60.0, 59.0, 58.0],
                    },
                }
            )
        raise AssertionError(f"unexpected URL {url}")


def test_weather_alpha_backtester_writes_accepted_report_with_real_labels(tmp_path):
    cfg = get_polymarket_cli_config(
        market_vertical="weather",
        search_symbols=["WEATHER"],
        _data_dir_override=tmp_path / "pm_weather_alpha",
    )
    backtester = WeatherAlphaBacktester(
        config=cfg,
        session=_FakeAlphaSession(),
        output_dir=tmp_path / "alpha",
    )

    report = backtester.run(
        max_events=1,
        max_markets=5,
        min_volume=0.0,
        lead_days=1,
        past_days=7,
        min_edge_gap=0.08,
        min_records=1,
        min_candidates=1,
    )

    assert report["record_count"] == 1
    assert report["candidate_count"] == 1
    assert report["raw_heuristic_verdict"]["accepted_for_live_weather_trading"] is True
    assert report["deployment_verdict"]["accepted_for_live_weather_trading"] is False
    assert "need_at_least_100_records" in report["deployment_verdict"]["blockers"]
    assert report["model_brier"] < report["market_brier"]
    assert (tmp_path / "alpha" / "weather_alpha_records.jsonl").exists()
    assert (tmp_path / "alpha" / "latest_weather_alpha_report.md").exists()


def test_weather_alpha_backtester_can_use_historical_forecast_source(tmp_path):
    cfg = get_polymarket_cli_config(
        market_vertical="weather",
        search_symbols=["WEATHER"],
        _data_dir_override=tmp_path / "pm_weather_alpha_hist",
    )
    backtester = WeatherAlphaBacktester(
        config=cfg,
        session=_FakeAlphaSession(),
        output_dir=tmp_path / "alpha_hist",
    )

    report = backtester.run(
        max_events=1,
        max_markets=5,
        min_volume=0.0,
        lead_days=1,
        past_days=1,
        min_edge_gap=0.08,
        min_records=1,
        min_candidates=1,
        forecast_source="historical_forecast",
    )
    records_path = tmp_path / "alpha_hist" / "weather_alpha_records.jsonl"
    record = __import__("json").loads(records_path.read_text().splitlines()[0])

    assert report["record_count"] == 1
    assert report["forecast_sources"] == ["open_meteo_historical_forecast"]
    assert "historical_forecast_source_not_asof_safe" in report["deployment_verdict"]["blockers"]
    assert record["forecast_source"] == "open_meteo_historical_forecast"


def test_weather_alpha_does_not_use_latest_high_res_cache_for_historical_record(tmp_path):
    cache_dir = tmp_path / "high_res_cache"
    source_dir = cache_dir / "noaa_hrrr"
    source_dir.mkdir(parents=True)
    (source_dir / "latest.json").write_text(
        __import__("json").dumps(
            {
                "source_id": "noaa_hrrr",
                "run_id": "noaa_hrrr:current:latest",
                "forecast_metrics": {"high_temperature_f": 99.0},
            }
        ),
        encoding="utf-8",
    )
    cfg = get_polymarket_cli_config(
        market_vertical="weather",
        search_symbols=["WEATHER"],
        weather_high_resolution_sources=["noaa_hrrr"],
        weather_high_resolution_cache_dir=str(cache_dir),
        _data_dir_override=tmp_path / "pm_weather_alpha_no_latest",
    )
    backtester = WeatherAlphaBacktester(
        config=cfg,
        session=_FakeAlphaSession(),
        output_dir=tmp_path / "alpha_no_latest",
    )
    market = CLIMarket(
        condition_id="weather-alpha-no-latest-1",
        question="Will NYC high temperature be above 75F on May 3?",
        symbol="WEATHER",
        yes_token_id="1001",
        no_token_id="1002",
        yes_price=0.5,
        no_price=0.5,
        liquidity=1000.0,
        volume_24h=100.0,
        end_date=datetime(2026, 5, 3, 23, 59),
    )
    parsed = WeatherMarketParse(
        location=WeatherLocation("New York City", 40.7128, -74.0060, ("new york city", "nyc")),
        metric="temperature_high",
        operator=">",
        threshold=75.0,
        upper_threshold=None,
        threshold_unit="F",
        target_date=date(2026, 5, 3),
    )

    record = backtester._record_from_inputs(
        market=market,
        parsed=parsed,
        metrics={"high_temperature_f": 81.0},
        yes_price=0.45,
        yes_resolved=True,
        probability=0.72,
        lead_days=1,
        asof_time=datetime(2026, 5, 2, 12, 0),
        price_source="fixture",
        forecast_source="open_meteo_previous_runs",
    )

    high_res = record.high_resolution_sources[0]
    assert high_res["status"] == "parser_required"
    assert high_res["parsed_snapshot"]["status"] == "artifact_missing"
    assert high_res["parsed_snapshot"]["forecast_metrics"] == {}
    assert "high_resolution_artifact_missing:noaa_hrrr" in high_res["blockers"]


def test_weather_alpha_gate_blocks_when_required_high_res_is_not_covered(tmp_path):
    cfg = get_polymarket_cli_config(
        market_vertical="weather",
        search_symbols=["WEATHER"],
        weather_require_high_resolution_confirmation=True,
        _data_dir_override=tmp_path / "pm_weather_alpha_high_res_gate",
    )
    backtester = WeatherAlphaBacktester(
        config=cfg,
        session=_FakeAlphaSession(),
        output_dir=tmp_path / "alpha_high_res_gate",
    )

    report = backtester.run(
        max_events=1,
        max_markets=5,
        min_volume=0.0,
        lead_days=1,
        past_days=7,
        min_edge_gap=0.08,
        min_records=1,
        min_candidates=1,
    )

    assert "high_resolution_alpha_coverage_incomplete" in report["raw_heuristic_verdict"]["blockers"]
    assert "high_resolution_alpha_coverage_incomplete" in report["deployment_verdict"]["blockers"]
    assert report["deployment_verdict"]["accepted_for_live_weather_trading"] is False


def test_weather_alpha_parses_unambiguous_gamma_resolution():
    assert WeatherAlphaBacktester.parse_yes_resolution(
        {"outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"1\", \"0\"]", "closed": True}
    ) is True
    assert WeatherAlphaBacktester.parse_yes_resolution(
        {"outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0\", \"1\"]", "closed": True}
    ) is False
    assert WeatherAlphaBacktester.parse_yes_resolution(
        {"outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.5\", \"0.5\"]", "closed": True}
    ) is None
    assert WeatherAlphaBacktester.parse_yes_resolution(
        {"outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.99\", \"0.01\"]", "active": True, "closed": False}
    ) is None


def test_weather_price_history_selects_only_asof_or_prior_points():
    asof = datetime(2026, 5, 2, 12, 0, 0)
    point = select_price_at_or_before(
        [
            {"t": int(asof.timestamp()) + 60, "p": 0.20},
            {"t": int(asof.timestamp()) - 300, "p": 0.40},
        ],
        asof,
        token_id="yes-token",
    )

    assert point is not None
    assert point.price == 0.40
    assert point.age_hours > 0


def _calibration_row(index, target_date, yes_resolved):
    return {
        "market_id": f"m-{index}",
        "question": f"Weather calibration fixture {index}",
        "target_date": target_date,
        "metric": "temperature_high",
        "location": "Fixture City",
        "yes_price": 0.50,
        "model_probability": 0.90 if yes_resolved else 0.10,
        "yes_resolved": yes_resolved,
    }


def test_weather_alpha_calibration_accepts_chronological_holdout_signal():
    rows = []
    for date_index, target_date in enumerate(["2026-05-01", "2026-05-02", "2026-05-03"]):
        for row_index in range(4):
            yes_resolved = (row_index + date_index) % 2 == 0
            rows.append(_calibration_row(len(rows), target_date, yes_resolved))

    report = WeatherAlphaCalibrationEvaluator().evaluate(
        rows,
        min_records=6,
        min_candidates=2,
        min_target_dates=3,
    )

    assert report["deployment_verdict"]["accepted_for_live_weather_trading"] is True
    assert report["holdout_score"]["candidate_roi_per_1usd"] > 0
    assert report["holdout_score"]["brier"] < report["holdout_market_at_policy_gap"]["brier"]


def test_weather_alpha_calibration_rejects_single_date_overfit():
    rows = [_calibration_row(index, "2026-05-02", index % 2 == 0) for index in range(10)]

    report = WeatherAlphaCalibrationEvaluator().evaluate(
        rows,
        min_records=6,
        min_candidates=2,
        min_target_dates=3,
    )

    assert report["deployment_verdict"]["accepted_for_live_weather_trading"] is False
    assert "need_at_least_3_target_dates" in report["deployment_verdict"]["blockers"]
    assert "chronological_holdout_unavailable" in report["deployment_verdict"]["blockers"]
