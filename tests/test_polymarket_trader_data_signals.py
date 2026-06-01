from datetime import datetime, timedelta

from src.agents.polymarket_trader.config import get_polymarket_cli_config
from src.agents.polymarket_trader.data_signals import ExchangeDataSignals
from src.agents.polymarket_trader.models import CLIMarket
from src.agents.polymarket_trader.weather_signals import WeatherDataSignals


def test_get_signals_adds_price_anchor_direction_and_exchange_summary(monkeypatch):
    signals = ExchangeDataSignals()

    def fake_fetch(_symbols):
        return {
            "ETH": {
                "funding": "0.0006",
                "midPx": "2403.45",
                "markPx": "2403.4",
                "oraclePx": "2404.6",
                "prevDayPx": "2323.7",
            }
        }

    monkeypatch.setattr(signals, "_fetch_hyperliquid_market_context", fake_fetch)

    result = signals.get_signals(["ETH"])

    assert set(result.keys()) == {"ETH"}
    eth = result["ETH"]
    assert eth["funding_signal"] == "bearish"
    assert eth["inferred_price"] == 2403.45
    assert eth["direction"] == "up"
    assert eth["daily_move_pct"] > 3.0
    assert eth["daily_volatility_pct"] >= 5.0
    assert "spot ~$2,403" in eth["exchange_signal"]
    assert "funding bearish" in eth["exchange_signal"]


def test_get_signals_reuses_cached_subset_and_price_fallback(monkeypatch):
    signals = ExchangeDataSignals()
    calls = []

    def fake_fetch(symbols):
        calls.append(tuple(symbols))
        return {
            "BTC": {
                "funding": "0.0",
                "oraclePx": "65000",
                "prevDayPx": "65000",
            },
            "ETH": {
                "funding": "0.0",
                "markPx": "2400",
                "prevDayPx": "2410",
            },
        }

    monkeypatch.setattr(signals, "_fetch_hyperliquid_market_context", fake_fetch)

    full = signals.get_signals(["BTC", "ETH"])
    subset = signals.get_signals(["ETH"])

    assert len(calls) == 1
    assert set(full.keys()) == {"BTC", "ETH"}
    assert set(subset.keys()) == {"ETH"}
    assert full["BTC"]["inferred_price"] == 65000.0
    assert full["BTC"]["direction"] == "flat"
    assert subset["ETH"]["inferred_price"] == 2400.0
    assert subset["ETH"]["direction"] == "down"


class _FakeWeatherResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeWeatherSession:
    def __init__(self):
        self.params = None

    def get(self, _url, params=None, timeout=None):
        self.params = params
        return _FakeWeatherResponse(
            {
                "timezone": "America/New_York",
                "hourly": {
                    "time": [
                        "2026-05-03T00:00",
                        "2026-05-03T01:00",
                        "2026-05-03T02:00",
                    ],
                    "temperature_2m": [72.0, 78.0, 81.0],
                    "precipitation": [0.0, 0.0, 0.0],
                    "rain": [0.0, 0.0, 0.0],
                    "snowfall": [0.0, 0.0, 0.0],
                    "wind_speed_10m": [5.0, 6.0, 8.0],
                    "wind_gusts_10m": [9.0, 10.0, 12.0],
                },
            }
        )


def _weather_market():
    return CLIMarket(
        condition_id="weather-nyc-1",
        question="Will NYC high temperature be above 75F on May 3?",
        symbol="WEATHER",
        yes_token_id="701",
        no_token_id="702",
        yes_price=0.45,
        no_price=0.55,
        liquidity=1000.0,
        volume_24h=100.0,
        end_date=datetime.utcnow() + timedelta(hours=12),
        market_type="bullish",
        price_target=75.0,
    )


def test_weather_data_signals_builds_market_specific_forecast_context():
    cfg = get_polymarket_cli_config(market_vertical="weather", weather_forecast_days=3)
    fake_session = _FakeWeatherSession()
    weather = WeatherDataSignals(cfg, session=fake_session)

    context = weather.get_context_for_market(_weather_market())

    assert context["status"] == "ok"
    assert context["location"] == "New York City"
    assert context["metric"] == "temperature_high"
    assert context["forecast_metrics"]["high_temperature_f"] == 81.0
    assert context["weather_probability"] > 0.5
    assert context["weather_edge_percent"] > 0
    assert context["recommended_side"] == "YES"
    assert fake_session.params["temperature_unit"] == "fahrenheit"


def test_weather_data_signals_scores_temperature_range_contract():
    cfg = get_polymarket_cli_config(market_vertical="weather", weather_forecast_days=3)
    weather = WeatherDataSignals(cfg, session=_FakeWeatherSession())
    market = CLIMarket(
        condition_id="weather-houston-range",
        question="Will the highest temperature in Houston be between 78-82F on May 3?",
        symbol="WEATHER",
        yes_token_id="711",
        no_token_id="712",
        yes_price=0.30,
        no_price=0.70,
        liquidity=1000.0,
        volume_24h=100.0,
        end_date=datetime.utcnow() + timedelta(hours=12),
        market_type="neutral",
    )

    context = weather.get_context_for_market(market)

    assert context["status"] == "ok"
    assert context["location"] == "Houston"
    assert context["operator"] == "between"
    assert context["threshold"] == 78.0
    assert context["upper_threshold"] == 82.0
    assert context["weather_probability"] > 0.2


def test_weather_data_signals_parses_exact_celsius_city_contract():
    cfg = get_polymarket_cli_config(market_vertical="weather", weather_forecast_days=3)
    weather = WeatherDataSignals(cfg, session=_FakeWeatherSession())
    market = CLIMarket(
        condition_id="weather-munich-celsius",
        question="Will the highest temperature in Munich be 27C on May 3?",
        symbol="WEATHER",
        yes_token_id="721",
        no_token_id="722",
        yes_price=0.30,
        no_price=0.70,
        liquidity=1000.0,
        volume_24h=100.0,
        end_date=datetime.utcnow() + timedelta(hours=12),
        market_type="neutral",
    )

    context = weather.get_context_for_market(market)

    assert context["status"] == "ok"
    assert context["location"] == "Munich"
    assert context["operator"] == "between"
    assert round(context["threshold"], 1) == 79.7
    assert round(context["upper_threshold"], 1) == 81.5


def test_weather_data_signals_parses_celsius_or_below_as_threshold():
    cfg = get_polymarket_cli_config(market_vertical="weather", weather_forecast_days=3)
    weather = WeatherDataSignals(cfg, session=_FakeWeatherSession())
    market = CLIMarket(
        condition_id="weather-munich-celsius-below",
        question="Will the highest temperature in Munich be 27C or below on May 3?",
        symbol="WEATHER",
        yes_token_id="725",
        no_token_id="726",
        yes_price=0.30,
        no_price=0.70,
        liquidity=1000.0,
        volume_24h=100.0,
        end_date=datetime.utcnow() + timedelta(hours=12),
        market_type="neutral",
    )

    context = weather.get_context_for_market(market)

    assert context["status"] == "ok"
    assert context["operator"] == "below"
    assert round(context["threshold"], 1) == 80.6
    assert context["upper_threshold"] is None


def test_weather_data_signals_uses_target_date_and_geocodes_global_city():
    class GeoForecastSession:
        def get(self, url, params=None, timeout=None):
            if "geocoding-api" in url:
                return _FakeWeatherResponse(
                    {"results": [{"name": "Tokyo", "latitude": 35.6762, "longitude": 139.6503}]}
                )
            return _FakeWeatherResponse(
                {
                    "timezone": "Asia/Tokyo",
                    "hourly": {
                        "time": [
                            "2026-05-01T00:00",
                            "2026-05-01T01:00",
                            "2026-05-02T00:00",
                            "2026-05-02T01:00",
                        ],
                        "temperature_2m": [90.0, 92.0, 59.0, 60.0],
                        "precipitation": [0.0, 0.0, 0.0, 0.0],
                        "rain": [0.0, 0.0, 0.0, 0.0],
                        "snowfall": [0.0, 0.0, 0.0, 0.0],
                        "wind_speed_10m": [5.0, 5.0, 5.0, 5.0],
                        "wind_gusts_10m": [8.0, 8.0, 8.0, 8.0],
                    },
                }
            )

    cfg = get_polymarket_cli_config(market_vertical="weather", weather_forecast_days=3)
    weather = WeatherDataSignals(cfg, session=GeoForecastSession())
    market = CLIMarket(
        condition_id="weather-tokyo-target-date",
        question="Will the highest temperature in Tokyo be 16C on May 2?",
        symbol="WEATHER",
        yes_token_id="731",
        no_token_id="732",
        yes_price=0.05,
        no_price=0.95,
        liquidity=1000.0,
        volume_24h=100.0,
        end_date=datetime(2026, 5, 2, 12, 0),
        market_type="neutral",
    )

    context = weather.get_context_for_market(market)

    assert context["status"] == "ok"
    assert context["location"] == "Tokyo"
    assert context["target_date"] == "2026-05-02"
    assert context["forecast_metrics"]["high_temperature_f"] == 60.0


def test_exchange_data_signals_routes_weather_markets_to_weather_adapter(monkeypatch):
    cfg = get_polymarket_cli_config(market_vertical="weather")
    signals = ExchangeDataSignals(cfg)

    monkeypatch.setattr(
        signals.weather,
        "get_market_context",
        lambda markets: {markets[0].condition_id: {"status": "ok", "domain": "weather"}},
    )

    result = signals.get_market_context([_weather_market()])

    assert result == {"weather-nyc-1": {"status": "ok", "domain": "weather"}}
