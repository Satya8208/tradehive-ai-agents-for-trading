import json
from datetime import date

from src.agents.polymarket_trader.config import ExecutionMode, get_polymarket_cli_config
from src.agents.polymarket_trader.weather_alpha import WeatherAlphaRecord
from src.agents.polymarket_trader.weather_edge_lab import (
    WeatherEdgeLabRunner,
    WeatherEdgeModelBuilder,
    WeatherExecutionCostModel,
    WeatherFeatureBuilder,
    WeatherPaperExportBuilder,
    WeatherPromotionGateEvaluator,
)


def _alpha_record(index, target_date, yes_resolved=True, forecast_source="open_meteo_previous_day1", probability=None):
    if probability is None:
        probability = 0.82 if yes_resolved else 0.18
    yes_price = 0.46
    selected_side = "YES" if probability >= yes_price else "NO"
    selected_win = yes_resolved if selected_side == "YES" else not yes_resolved
    side_price = yes_price if selected_side == "YES" else 1.0 - yes_price
    pnl = ((1.0 - side_price) / side_price) if selected_win else -1.0
    record = WeatherAlphaRecord(
        market_id=f"weather-lab-{index}",
        question=f"Will NYC high temperature be above 75F on {target_date}?",
        slug=f"weather-lab-{index}",
        end_date=f"{target_date}T12:00:00",
        target_date=target_date,
        location="New York City" if index % 2 == 0 else "Chicago",
        metric="temperature_high",
        operator="above",
        threshold=75.0,
        upper_threshold=None,
        lead_days=index % 2,
        asof_time=f"{target_date}T00:00:00",
        yes_price=yes_price,
        model_probability=probability,
        edge=round(probability - yes_price, 4),
        recommended_side=selected_side,
        side_price=side_price,
        yes_resolved=yes_resolved,
        selected_win=selected_win,
        pnl_per_usd=round(pnl, 4),
        price_source="clob_prices_history",
        forecast_source=forecast_source,
        forecast_metrics={"high_temperature_f": 81.0 if yes_resolved else 68.0},
    )
    record.book_depth = 100.0
    return record


def test_weather_source_adapters_normalize_and_fail_closed():
    row = _alpha_record(1, "2026-05-01", yes_resolved=True)
    records = WeatherFeatureBuilder().build_records(
        [row],
        ["polymarket_gamma", "open_meteo_previous_runs", "ncep_nomads"],
    )

    record = records[0]

    assert record.source_statuses["polymarket_gamma"] == "live_safe"
    assert record.source_statuses["open_meteo_previous_runs"] == "live_safe"
    assert record.source_statuses["ncep_nomads"] == "unavailable"
    assert record.source_statuses["station_bias"] == "missing_history"
    assert record.source_statuses["high_resolution_manifests"] == "manifest_ready"
    assert {item["source_id"] for item in record.high_resolution_sources} == {"noaa_hrrr", "noaa_nbm"}
    assert "unavailable_requires_grib_parser:ncep_nomads" in record.blockers
    assert record.market_yes_price == 0.46
    assert record.source_probabilities["open_meteo_previous_runs"] == 0.82


class _FeatureResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _NWSFeatureSession:
    def get(self, url, params=None, headers=None, timeout=None):
        if "api.weather.gov/points" in url:
            return _FeatureResponse(
                {"properties": {"forecastHourly": "https://api.weather.gov/gridpoints/OKX/33,35/forecast/hourly"}}
            )
        if "forecast/hourly" in url:
            today = date.today().isoformat()
            return _FeatureResponse(
                {
                    "properties": {
                        "periods": [
                            {
                                "startTime": f"{today}T12:00:00+00:00",
                                "temperature": 82,
                                "windSpeed": "12 mph",
                                "probabilityOfPrecipitation": {"value": 20},
                            }
                        ]
                    }
                }
            )
        raise AssertionError(f"unexpected URL {url}")


class _METARFeatureSession:
    def get(self, url, params=None, headers=None, timeout=None):
        assert "aviationweather.gov/api/data/metar" in url
        assert params["ids"] == "KNYC"
        return _FeatureResponse([{"icaoId": "KNYC", "temp": 30.0, "wspd": 10, "wgst": 18, "rawOb": "KNYC METAR"}])


def test_nws_adapter_builds_live_safe_probability_for_current_target_date():
    row = _alpha_record(2, date.today().isoformat(), yes_resolved=True)
    builder = WeatherFeatureBuilder(session=_NWSFeatureSession())

    record = builder.build_records([row], ["nws_api"])[0]

    assert record.source_statuses["nws_api"] == "live_safe"
    assert record.source_probabilities["nws_api"] > 0.5
    assert record.source_features["nws_api"]["features"]["forecast_metrics"]["high_temperature_f"] == 82


def test_awc_metar_adapter_maps_station_and_normalizes_observation():
    row = _alpha_record(6, date.today().isoformat(), yes_resolved=True)
    builder = WeatherFeatureBuilder(session=_METARFeatureSession())

    record = builder.build_records([row], ["noaa_awc_metar"])[0]

    assert record.source_statuses["noaa_awc_metar"] == "live_safe"
    assert record.source_features["noaa_awc_metar"]["features"]["station"] == "KNYC"
    assert record.source_features["noaa_awc_metar"]["features"]["forecast_metrics"]["high_temperature_f"] == 86.0


def test_heavy_weather_sources_emit_actionable_request_manifests():
    row = _alpha_record(4, "2026-05-01", yes_resolved=True)
    record = WeatherFeatureBuilder().build_records([row], ["noaa_hrrr", "noaa_nexrad", "ecmwf_open_data"])[0]

    assert record.source_statuses["noaa_hrrr"] == "unavailable"
    assert "request_url" in record.source_features["noaa_hrrr"]["features"]
    assert "unavailable_requires_grib_parser:noaa_hrrr" in record.blockers
    assert record.source_features["noaa_nexrad"]["features"]["radar_station"] == "KOKX"
    assert "unavailable_requires_radar_parser:noaa_nexrad" in record.blockers


def test_optional_parser_blockers_are_reported_but_do_not_fail_promotion_gate():
    row = WeatherFeatureBuilder().build_records(
        [_alpha_record(5, "2026-05-01", yes_resolved=True)],
        ["open_meteo_previous_runs", "noaa_hrrr"],
    )[0]
    report = {
        "record_count": 300,
        "target_date_count": 8,
        "best_result": {
            "model_name": "heuristic_baseline",
            "edge_gap": 0.04,
            "holdout": {
                "candidate_count": 75,
                "candidate_roi_after_cost": 0.10,
                "brier": 0.20,
                "log_loss": 0.40,
                "max_single_location_date_metric_pnl_share": 0.10,
                "top_candidates": [{"clob_price_age_hours": 0.5}],
            },
        },
        "market_baseline": {"holdout": {"brier": 0.25, "log_loss": 0.50}},
    }

    verdict = WeatherPromotionGateEvaluator().evaluate([row], report, paper_export_requested=True)

    assert "unavailable_requires_grib_parser:noaa_hrrr" in row.blockers
    assert verdict["accepted_for_paper_trade"] is True


def test_weather_model_variants_produce_bounded_probabilities():
    rows = [
        _alpha_record(index, f"2026-05-{1 + index // 4:02d}", yes_resolved=index % 2 == 0)
        for index in range(12)
    ]
    feature_records = WeatherFeatureBuilder().build_records(rows, ["open_meteo_previous_runs"])
    train, holdout, _dates = WeatherEdgeModelBuilder._split_chronological(feature_records)
    predictions, _configs = WeatherEdgeModelBuilder()._build_prediction_sets(train, holdout)

    assert set(predictions) == {
        "heuristic_baseline",
        "market_forecast_blend",
        "logistic_calibration",
        "isotonic_calibration",
        "source_ensemble",
        "shrink_to_market",
    }
    for model_predictions in predictions.values():
        assert model_predictions
        assert all(0.02 <= value <= 0.98 for value in model_predictions.values())


def test_weather_execution_cost_model_reduces_gross_edge():
    row = WeatherFeatureBuilder().build_records([_alpha_record(1, "2026-05-01")], ["open_meteo_previous_runs"])[0]

    scored = WeatherExecutionCostModel().score(row, 0.76)

    assert scored["gross_edge_abs"] > scored["net_edge_abs"]
    assert scored["edge_haircut"] > 0


def test_weather_paper_export_is_empty_unless_gates_pass(tmp_path):
    builder = WeatherPaperExportBuilder()
    backtest = {
        "best_result": {
            "model_name": "heuristic_baseline",
            "edge_gap": 0.04,
            "holdout": {
                "top_candidates": [
                    {
                        "market_id": "weather-lab-1",
                        "question": "Will NYC high temperature be above 75F?",
                        "target_date": "2026-05-01",
                        "location": "New York City",
                        "metric": "temperature_high",
                        "lead_days": 1,
                        "asof_time": "2026-05-01T00:00:00",
                        "selected_side": "YES",
                        "market_yes_price": 0.46,
                        "probability": 0.72,
                        "net_edge": 0.23,
                        "blockers": [],
                    }
                ]
            },
        }
    }

    blocked = builder.export([], backtest, {"accepted_for_paper_trade": False, "blockers": ["blocked"]}, tmp_path, True)
    accepted = builder.export([], backtest, {"accepted_for_paper_trade": True, "blockers": []}, tmp_path / "ok", True)

    assert blocked["paper_recommendation_count"] == 0
    assert accepted["paper_recommendation_count"] == 1
    assert accepted["live_order_enabled"] is False
    exported = json.loads((tmp_path / "ok" / "latest_paper_recommendations.jsonl").read_text().splitlines()[0])
    assert exported["execution_mode"] == "paper"
    assert exported["live_order_enabled"] is False


def test_weather_paper_export_uses_side_price_for_no_candidates(tmp_path):
    builder = WeatherPaperExportBuilder()
    backtest = {
        "best_result": {
            "model_name": "heuristic_baseline",
            "edge_gap": 0.04,
            "holdout": {
                "top_candidates": [
                    {
                        "market_id": "weather-lab-no",
                        "question": "Will NYC high temperature be above 75F?",
                        "target_date": "2026-05-01",
                        "location": "New York City",
                        "metric": "temperature_high",
                        "lead_days": 1,
                        "asof_time": "2026-05-01T00:00:00",
                        "selected_side": "NO",
                        "market_yes_price": 0.46,
                        "side_price": 0.54,
                        "probability": 0.22,
                        "net_edge": -0.20,
                        "blockers": [],
                    }
                ]
            },
        }
    }

    accepted = builder.export([], backtest, {"accepted_for_paper_trade": True, "blockers": []}, tmp_path / "no", True)
    exported = json.loads((tmp_path / "no" / "latest_paper_recommendations.jsonl").read_text().splitlines()[0])

    assert accepted["paper_recommendation_count"] == 1
    assert exported["side"] == "NO"
    assert exported["limit_price"] == 0.54


def test_weather_edge_lab_runs_fake_dataset_to_matrix_and_artifacts(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        search_symbols=["WEATHER"],
        _data_dir_override=tmp_path / "pm_data",
    )
    rows = [
        _alpha_record(index, f"2026-05-{1 + index // 4:02d}", yes_resolved=index % 2 == 0)
        for index in range(12)
    ]
    runner = WeatherEdgeLabRunner(config=cfg, output_dir=tmp_path / "lab")

    report = runner.run_from_alpha_records(
        rows,
        lead_days=[0, 1],
        edge_gaps=[0.04, 0.08],
        sources=["open_meteo_previous_runs"],
        paper_export=True,
    )

    assert report["mode"] == "research_paper_only"
    assert report["live_trade_export_enabled"] is False
    assert report["dataset"]["record_count"] == 12
    assert report["backtest"]["target_date_count"] == 3
    assert len(report["backtest"]["matrix"]) == 12
    assert report["backtest"]["return_summary"]["rows"]
    assert report["backtest"]["return_summary"]["unit_stake"] == "1 USD per selected candidate"
    assert report["promotion_verdict"]["accepted_for_paper_trade"] is False
    assert "need_at_least_300_resolved_records" in report["promotion_verdict"]["blockers"]
    assert report["paper_export"]["paper_recommendation_count"] == 0
    assert (tmp_path / "lab" / "datasets" / "weather_edge_lab_records.jsonl").exists()
    assert (tmp_path / "lab" / "features" / "weather_edge_lab_features.jsonl").exists()
    assert (tmp_path / "lab" / "backtests" / "latest_backtest_report.json").exists()
    assert (tmp_path / "lab" / "models" / "latest_model_matrix.json").exists()
    assert (tmp_path / "lab" / "latest_weather_edge_lab_report.md").exists()
    markdown = (tmp_path / "lab" / "latest_weather_edge_lab_report.md").read_text()
    assert "## Logic" in markdown
    assert "## Returns Matrix" in markdown


def test_historical_forecast_source_is_research_only_and_blocks_paper(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        search_symbols=["WEATHER"],
        _data_dir_override=tmp_path / "pm_data",
    )
    rows = [
        _alpha_record(
            index,
            f"2026-05-{1 + index // 4:02d}",
            yes_resolved=index % 2 == 0,
            forecast_source="open_meteo_historical_forecast",
        )
        for index in range(12)
    ]
    runner = WeatherEdgeLabRunner(config=cfg, output_dir=tmp_path / "lab")

    report = runner.run_from_alpha_records(
        rows,
        lead_days=[1],
        edge_gaps=[0.04],
        sources=["open_meteo_historical_forecast"],
        paper_export=True,
    )

    assert report["promotion_verdict"]["accepted_for_paper_trade"] is False
    assert "research_only_source:open_meteo_historical_forecast" in report["promotion_verdict"]["blockers"]
    assert report["paper_export"]["paper_recommendation_count"] == 0
