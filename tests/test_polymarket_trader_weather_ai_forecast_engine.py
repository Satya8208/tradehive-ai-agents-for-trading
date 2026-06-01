import json
from datetime import datetime

from src.agents.polymarket_trader.config import ExecutionMode, get_polymarket_cli_config
from src.agents.polymarket_trader.models import CLIMarket
from src.agents.polymarket_trader.weather_ai_decision import WeatherAIDecisioner
from src.agents.polymarket_trader.weather_candidate_ranker import WeatherCandidateRanker
from src.agents.polymarket_trader.weather_contracts import FEATURE_SCHEMA_VERSION, WeatherAIDecision
from src.agents.polymarket_trader.weather_evidence_store import WeatherEvidenceStore
from src.agents.polymarket_trader.weather_signals import WeatherDataSignals


class _WeatherResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _ForecastRunSession:
    def get(self, url, params=None, timeout=None):
        if "previous-runs-api.open-meteo.com" in url:
            return _WeatherResponse(
                {
                    "timezone": "America/New_York",
                    "hourly": {
                        "time": ["2026-05-03T00:00", "2026-05-03T12:00"],
                        "temperature_2m_previous_day1": [70.0, 71.0],
                    },
                }
            )
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


class _FakeAIDecisioner:
    def __init__(self):
        self.called_with = []

    def decide(self, forecast_packet):
        self.called_with.append(forecast_packet)
        return WeatherAIDecision(
            status="ok",
            provider="openai",
            model_name="gpt-5.5",
            p_yes=0.79,
            side="YES",
            strategy_lane="forecast_run_shock",
            confidence=0.72,
            uncertainty_band={"low": 0.68, "high": 0.86},
            trade_thesis="Dry-run model check saw a forecast-run shock.",
            data_quality="medium",
            recommended_size_usd=6.0,
        )


def _market():
    return CLIMarket(
        condition_id="weather-ai-forecast-1",
        question="Will NYC high temperature be above 75F on May 3?",
        symbol="WEATHER",
        yes_token_id="yes",
        no_token_id="no",
        yes_price=0.42,
        no_price=0.58,
        liquidity=1500.0,
        volume_24h=100.0,
        end_date=datetime(2026, 5, 3, 23, 59),
    )


def test_forecast_model_packet_joins_previous_run_high_res_and_market_context(tmp_path):
    cache_dir = tmp_path / "high_res"
    (cache_dir / "noaa_hrrr").mkdir(parents=True)
    (cache_dir / "noaa_hrrr" / "latest.json").write_text(
        json.dumps(
            {
                "source_id": "noaa_hrrr",
                "run_id": "noaa_hrrr:test:f012",
                "forecast_metrics": {"high_temperature_f": 85.0},
                "latitude": 40.7,
                "longitude": -74.0,
            }
        ),
        encoding="utf-8",
    )
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        weather_forecast_days=3,
        weather_high_resolution_cache_dir=str(cache_dir),
        weather_ai_forecast_engine_enabled=True,
    )
    signals = WeatherDataSignals(cfg, session=_ForecastRunSession())
    fake_ai = _FakeAIDecisioner()
    signals.ai_decisioner = fake_ai
    signals.set_market_tape_snapshots(
        [
            {
                "market_id": _market().condition_id,
                "executable_yes_price": 0.43,
                "executable_no_price": 0.59,
                "executable_price_source": "orderbook_best_ask",
                "spread": 0.02,
                "yes_book": {"ask_depth_usd": 40.0},
                "no_book": {"ask_depth_usd": 35.0},
                "blockers": [],
            }
        ]
    )

    context = signals.get_context_for_market(_market())
    packet = context["forecast_model_packet"]

    assert packet["schema_version"] == "weather_forecast_model_packet_v1"
    assert packet["execution_context"]["status"] == "market_tape_attached"
    assert "open_meteo_previous_runs" in packet["source_probabilities"]
    assert "noaa_hrrr" in packet["source_probabilities"]
    assert "forecast_run_shock" in packet["strategy_lanes"]
    assert any(row["delta_type"] == "current_vs_previous_run" for row in packet["forecast_deltas"])
    assert fake_ai.called_with
    assert context["ai_decision"]["status"] == "ok"
    assert context["ai_decision"]["model_name"] == "gpt-5.5"


def test_ai_decision_parser_accepts_strict_json_and_blocks_overconfidence():
    cfg = get_polymarket_cli_config(market_vertical="weather")
    parser = WeatherAIDecisioner(cfg)
    valid = parser.parse_decision(
        json.dumps(
            {
                "p_yes": 0.78,
                "side": "YES",
                "strategy_lane": "forecast_run_shock",
                "confidence": 0.74,
                "uncertainty_band": {"low": 0.67, "high": 0.86},
                "trade_thesis": "Fresh model run moved materially above the threshold.",
                "veto_reasons": [],
                "data_quality": "medium",
                "recommended_size_usd": 9.0,
            }
        ),
        forecast_packet={
            "model_disagreement": {"source_count": 2},
            "execution_context": {"status": "market_tape_attached"},
        },
    )

    assert valid.status == "ok"
    assert valid.usable_for_paper is True
    assert valid.p_yes == 0.78
    assert valid.side == "YES"

    blocked = parser.parse_decision(
        json.dumps(
            {
                "p_yes": 0.96,
                "side": "YES",
                "strategy_lane": "forecast_model_baseline",
                "confidence": 0.95,
                "uncertainty_band": {"low": 0.90, "high": 0.99},
                "trade_thesis": "Too confident on weak data.",
                "veto_reasons": [],
                "data_quality": "poor",
                "recommended_size_usd": 20.0,
            }
        ),
        forecast_packet={
            "model_disagreement": {"source_count": 1},
            "execution_context": {"status": "orderbook_depth_not_attached_to_signal_packet"},
        },
    )

    assert blocked.status == "invalid_decision"
    assert "weather_ai_overconfident_for_data_quality" in blocked.blockers
    assert "weather_ai_overconfident_single_source" in blocked.blockers


def test_candidate_ranker_uses_ai_probability_and_blocks_ai_veto(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.PAPER,
        market_vertical="weather",
        min_liquidity_usd=100.0,
        weather_min_probability_gap=0.08,
        _data_dir_override=tmp_path,
    )
    market = _market()
    context = {
        "status": "ok",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "weather_probability": 0.52,
        "weather_confidence": 0.45,
        "weather_edge_percent": 10.0,
        "recommended_side": "YES",
        "source_statuses": {"station_mapper": "ok", "open_meteo_forecast": "live_safe"},
        "ai_decision": {
            "status": "ok",
            "usable_for_paper": True,
            "p_yes": 0.81,
            "side": "YES",
            "confidence": 0.76,
            "strategy_lane": "forecast_run_shock",
            "recommended_size_usd": 7.0,
            "veto_reasons": [],
        },
        "forecast_model_packet": {"strategy_lanes": ["forecast_run_shock"]},
    }

    candidate = WeatherCandidateRanker(cfg).build_candidate(market, context)

    assert candidate.model_probability == 0.81
    assert candidate.size_usd == 7.0
    assert "ai_forecast_decision_used" in candidate.quality_flags
    assert not candidate.blockers

    veto_context = dict(context)
    veto_context["ai_decision"] = dict(context["ai_decision"])
    veto_context["ai_decision"]["veto_reasons"] = ["resolution source unclear"]
    vetoed = WeatherCandidateRanker(cfg).build_candidate(market, veto_context)

    assert "weather_ai_veto:resolution_source_unclear" in vetoed.blockers


def test_evidence_store_persists_forecast_packet_and_ai_decision(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        _data_dir_override=tmp_path,
    )
    store = WeatherEvidenceStore(cfg)
    market = _market()
    context = {
        market.condition_id: {
            "status": "ok",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "forecast_model_packet": {"schema_version": "weather_forecast_model_packet_v1"},
            "ai_decision": {"schema_version": "weather_ai_decision_v1", "status": "ok", "p_yes": 0.7},
        }
    }

    store.append_feature_snapshots([market], context, cycle=1, captured_at="2026-05-03T10:00:00")
    row = store.read_feature_snapshots()[0]

    assert row["forecast_model_packet"]["schema_version"] == "weather_forecast_model_packet_v1"
    assert row["ai_decision"]["schema_version"] == "weather_ai_decision_v1"
