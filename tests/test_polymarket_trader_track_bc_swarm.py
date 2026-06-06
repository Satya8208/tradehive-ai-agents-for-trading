from datetime import datetime, timedelta
import time
import json

from src.agents.polymarket_trader.config import get_polymarket_cli_config
from src.agents.polymarket_trader.models import CLIMarket, SwarmPrediction
from src.agents.polymarket_trader.swarm_analyzer import CLISwarmAnalyzer


def _market(**overrides):
    base = dict(
        condition_id="mkt-swarm",
        question="ETH above 3000 by tomorrow",
        symbol="ETH",
        yes_token_id="11",
        no_token_id="12",
        yes_price=0.59,
        no_price=0.41,
        liquidity=50000.0,
        volume_24h=25000.0,
        end_date=datetime.utcnow() + timedelta(hours=12),
        is_active=True,
        market_type="bullish",
        price_target=3200.0,
        spread=0.02,
    )
    base.update(overrides)
    return CLIMarket(**base)


def test_aggregate_predictions_abstains_when_edge_is_too_small(tmp_path):
    cfg = get_polymarket_cli_config(_data_dir_override=tmp_path / "swarm")
    analyzer = CLISwarmAnalyzer(config=cfg)
    market = _market(yes_price=0.59, no_price=0.41, price_target=None)
    predictions = [
        SwarmPrediction("deepseek", "deepseek-chat", "YES", 0.61, 0.68, "ok", 0.2),
        SwarmPrediction("xai", "grok-4-fast", "YES", 0.63, 0.72, "ok", 0.2),
    ]

    consensus = analyzer._aggregate_predictions(predictions, market, None)

    assert consensus.consensus_prediction == "ABSTAIN"
    assert analyzer.last_analysis_metadata["abstain_reason"] == "insufficient_price_edge"
    assert analyzer.last_analysis_metadata["plausibility"] == "unknown"


def test_aggregate_predictions_abstains_on_implausible_sigma_move(tmp_path):
    cfg = get_polymarket_cli_config(_data_dir_override=tmp_path / "swarm_sigma")
    analyzer = CLISwarmAnalyzer(config=cfg)
    market = _market(
        yes_price=0.54,
        no_price=0.46,
        price_target=3600.0,
        end_date=datetime.utcnow() + timedelta(hours=12),
    )
    price_context = {
        "ETH": {
            "inferred_price": 3000.0,
            "daily_volatility_pct": 5.0,
        }
    }
    plausibility = analyzer._build_plausibility_context(market, price_context)
    predictions = [
        SwarmPrediction("deepseek", "deepseek-chat", "YES", 0.82, 0.80, "ok", 0.2),
        SwarmPrediction("xai", "grok-4-fast", "YES", 0.78, 0.75, "ok", 0.2),
        SwarmPrediction("anthropic", "claude-3-haiku", "YES", 0.80, 0.78, "ok", 0.2),
    ]

    consensus = analyzer._aggregate_predictions(predictions, market, plausibility)

    assert consensus.consensus_prediction == "ABSTAIN"
    assert analyzer.last_analysis_metadata["abstain_reason"] == "sigma_implausible"
    assert analyzer.last_analysis_metadata["sigma_ratio"] is not None
    assert analyzer.last_analysis_metadata["sigma_ratio"] > 2.5


class _UnavailableModelFactory:
    def get_model(self, provider, model_name):
        return None

    def is_model_available(self, provider):
        return False


class _BrokenResponseModel:
    def generate_response(self, system_prompt, user_content, temperature=0.7, max_tokens=None):
        class _Resp:
            content = "not-json-response"
        return _Resp()


class _ParseFailureModelFactory:
    def get_model(self, provider, model_name):
        return _BrokenResponseModel()

    def is_model_available(self, provider):
        return True


class _ExceptionModel:
    def generate_response(self, system_prompt, user_content, temperature=0.7, max_tokens=None):
        raise RuntimeError("Error code: 402 - {'error': {'message': 'Insufficient Balance'}}")


class _ExceptionModelFactory:
    def get_model(self, provider, model_name):
        return _ExceptionModel()

    def is_model_available(self, provider):
        return True


def _partial_success_query(provider, model_name, prompt, role):
    if provider == "xai":
        return SwarmPrediction(provider, model_name, "YES", 0.65, 0.8, "ok", 0.2), None, None
    return None, "exception", "Error code: 402 - {'error': {'message': 'Insufficient Balance'}}"


def test_analyze_market_records_unavailable_swarm_models(tmp_path):
    cfg = get_polymarket_cli_config(_data_dir_override=tmp_path / "swarm_unavailable")
    analyzer = CLISwarmAnalyzer(config=cfg)
    analyzer.model_factory = _UnavailableModelFactory()

    consensus = analyzer.analyze_market(_market())

    assert consensus.consensus_prediction == "ABSTAIN"
    assert analyzer.last_analysis_metadata["abstain_reason"] == "swarm_models_unavailable"
    assert analyzer.last_analysis_metadata["successful_model_count"] == 0
    assert analyzer.last_analysis_metadata["measurement_boundary"] == "degraded_swarm"
    assert analyzer.last_analysis_metadata["analysis_cohort"] == "degraded_swarm"
    assert analyzer.last_analysis_metadata["runtime_ready"] is False
    assert all(item["status"] == "provider_unavailable" for item in analyzer.last_model_statuses)


def test_analyze_market_records_parse_failures(tmp_path):
    cfg = get_polymarket_cli_config(_data_dir_override=tmp_path / "swarm_parse_fail")
    analyzer = CLISwarmAnalyzer(config=cfg)
    analyzer.model_factory = _ParseFailureModelFactory()

    consensus = analyzer.analyze_market(_market())

    assert consensus.consensus_prediction == "ABSTAIN"
    assert analyzer.last_analysis_metadata["abstain_reason"] == "swarm_model_failures"
    assert analyzer.last_analysis_metadata["successful_model_count"] == 0
    assert all(item["status"] == "parse_failure" for item in analyzer.last_model_statuses)


def test_analyze_market_persists_exception_error_codes(tmp_path):
    cfg = get_polymarket_cli_config(_data_dir_override=tmp_path / "swarm_exceptions")
    analyzer = CLISwarmAnalyzer(config=cfg)
    analyzer.model_factory = _ExceptionModelFactory()

    consensus = analyzer.analyze_market(_market())

    assert consensus.consensus_prediction == "ABSTAIN"
    assert analyzer.last_analysis_metadata["abstain_reason"] == "swarm_model_failures"
    assert all(item["status"] == "exception" for item in analyzer.last_model_statuses)
    assert all(item["error_code"] == "insufficient_balance" for item in analyzer.last_model_statuses)
    assert all("Insufficient Balance" in item["error"] for item in analyzer.last_model_statuses)

    prediction_files = sorted((cfg.predictions_dir).glob("prediction_*.json"))
    assert prediction_files
    payload = json.loads(prediction_files[-1].read_text())
    assert all(item["error_code"] == "insufficient_balance" for item in payload["model_statuses"])


def test_analyze_market_marks_partial_consensus_shortfall_as_runtime_failure(tmp_path):
    cfg = get_polymarket_cli_config(_data_dir_override=tmp_path / "swarm_partial_failure")
    analyzer = CLISwarmAnalyzer(config=cfg)
    analyzer._query_model = _partial_success_query
    price_context = {
        "ETH": {
            "inferred_price": 3000.0,
            "daily_volatility_pct": 5.0,
            "daily_move_pct": 2.0,
        }
    }

    consensus = analyzer.analyze_market(_market(), price_context=price_context)

    assert consensus.consensus_prediction == "ABSTAIN"
    assert analyzer.last_analysis_metadata["abstain_reason"] == "insufficient_predictions_after_model_failures"
    assert analyzer.last_analysis_metadata["successful_model_count"] == 1
    assert analyzer.last_analysis_metadata["measurement_boundary"] == "degraded_swarm"
    assert analyzer.last_analysis_metadata["analysis_cohort"] == "single_model_control"
    assert analyzer.last_analysis_metadata["runtime_ready"] is False
    assert analyzer.last_analysis_metadata["current_price"] == 3000.0
    assert analyzer.last_analysis_metadata["sigma_ratio"] is not None
    statuses = {item["provider"]: item["status"] for item in analyzer.last_model_statuses}
    assert statuses["xai"] == "ok"
    assert statuses["openai"] == "exception"
    assert statuses["deepseek"] == "exception"

    prediction_files = sorted((cfg.predictions_dir).glob("prediction_*.json"))
    assert prediction_files
    payload = json.loads(prediction_files[-1].read_text())
    assert payload["abstain_reason"] == "insufficient_predictions_after_model_failures"
    assert payload["current_price"] == 3000.0
    assert payload["sigma_ratio"] is not None
    assert payload["measurement_boundary"] == "degraded_swarm"
    assert payload["analysis_cohort"] == "single_model_control"
    assert payload["runtime_ready"] is False


def test_analyze_market_timeout_returns_without_waiting_for_hung_workers(tmp_path):
    cfg = get_polymarket_cli_config(_data_dir_override=tmp_path / "swarm_timeout")
    cfg.swarm_timeout_seconds = 0.05
    analyzer = CLISwarmAnalyzer(config=cfg)

    def _slow_query(provider, model_name, prompt, role):
        time.sleep(0.3)
        return None, "slow_response"

    analyzer._query_model = _slow_query

    started = time.perf_counter()
    consensus = analyzer.analyze_market(_market())
    elapsed = time.perf_counter() - started

    assert elapsed < 0.25
    assert consensus.consensus_prediction == "ABSTAIN"
    assert analyzer.last_analysis_metadata["abstain_reason"] == "swarm_model_failures"
    assert all(item["status"] == "timeout" for item in analyzer.last_model_statuses)


def test_weather_prompt_includes_forecast_context(tmp_path):
    cfg = get_polymarket_cli_config(
        market_vertical="weather",
        search_symbols=["WEATHER"],
        _data_dir_override=tmp_path / "weather_prompt",
    )
    analyzer = CLISwarmAnalyzer(config=cfg)
    market = _market(
        condition_id="weather-swarm",
        question="Will NYC high temperature be above 75F on May 3?",
        symbol="WEATHER",
        yes_price=0.45,
        no_price=0.55,
        price_target=75.0,
    )
    context = {
        "weather-swarm": {
            "status": "ok",
            "location": "New York City",
            "metric": "temperature_high",
            "operator": "above",
            "threshold": 75.0,
            "threshold_unit": "F",
            "weather_probability": 0.72,
            "weather_edge_percent": 27.0,
            "weather_signal": "NYC forecast high 81F vs >=75F",
            "forecast_metrics": {"high_temperature_f": 81.0},
        }
    }

    prompt = analyzer._build_prompt(market, price_history=None, price_context=context)

    assert "Polymarket Weather Market" in prompt
    assert "Weather Forecast Signals" in prompt
    assert "Deterministic forecast YES probability: 72.0%" in prompt
    assert "NYC forecast high 81F" in prompt


def test_weather_probability_is_persisted_in_consensus_metadata(tmp_path):
    cfg = get_polymarket_cli_config(
        market_vertical="weather",
        search_symbols=["WEATHER"],
        _data_dir_override=tmp_path / "weather_consensus",
        weather_min_probability_gap=0.08,
    )
    analyzer = CLISwarmAnalyzer(config=cfg)
    market = _market(
        condition_id="weather-swarm-meta",
        question="Will NYC high temperature be above 75F on May 3?",
        symbol="WEATHER",
        yes_price=0.45,
        no_price=0.55,
        price_target=75.0,
    )
    predictions = [
        SwarmPrediction("deepseek", "deepseek-chat", "YES", 0.70, 0.85, "ok", 0.2),
        SwarmPrediction("xai", "grok-4-fast", "YES", 0.68, 0.80, "ok", 0.2),
    ]

    consensus = analyzer._aggregate_predictions(
        predictions,
        market,
        {
            "plausibility": "ok",
            "weather_probability": 0.78,
            "weather_edge_percent": 33.0,
            "weather_signal": "forecast clears",
        },
    )

    assert consensus.consensus_prediction == "YES"
    assert analyzer.last_analysis_metadata["weather_probability"] == 0.78
    assert analyzer.last_analysis_metadata["weather_edge_percent"] == 33.0
    assert analyzer.last_analysis_metadata["probability_gap"] >= 0.08
