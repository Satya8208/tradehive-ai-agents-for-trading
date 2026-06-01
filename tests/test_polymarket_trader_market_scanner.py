from datetime import datetime, timedelta

from src.agents.polymarket_trader.config import get_polymarket_cli_config
from src.agents.polymarket_trader.market_scanner import CLIMarketScanner
from src.agents.polymarket_trader.models import CLIMarket


class MarketScannerStubCLI:
    def __init__(self, payloads):
        self._payloads = payloads

    def search_markets(self, *args, **kwargs):
        return self._payloads


class WeatherTagScannerStubCLI(MarketScannerStubCLI):
    def _gamma_request(self, path, params=None):
        assert path == "/events"
        if params.get("offset", 0) > 0:
            return []
        return [
            {
                "slug": "highest-temperature-in-shenzhen-on-may-5",
                "title": "Highest temperature in Shenzhen on May 5?",
                "tags": [{"slug": "weather", "label": "Weather"}],
                "markets": [
                    {
                        "conditionId": "weather-tag-1",
                        "question": "Will the highest temperature in Shenzhen be 25°C on May 5?",
                        "slug": "highest-temperature-shenzhen-25c",
                        "clobTokenIds": ["7001", "7002"],
                        "outcomePrices": [0.33, 0.67],
                        "liquidityNum": 1200.0,
                        "volumeNum": 10.0,
                        "active": True,
                        "acceptingOrders": True,
                        "endDate": int((datetime.utcnow() + timedelta(hours=8)).timestamp()),
                    }
                ],
            }
        ]


def _valid_market_payload(clob_ids, question_suffix=""):
    end_ts = int((datetime.utcnow() + timedelta(hours=1)).timestamp())
    return {
        "question": f"ETH up or down{question_suffix}",
        "clobTokenIds": clob_ids,
        "outcomePrices": [0.52, 0.48],
        "liquidity": 12000.0,
        "volume24hr": 7000.0,
        "active": True,
        "acceptingOrders": True,
        "endDate": end_ts,
    }


def test_parse_cli_market_skips_invalid_datetime_and_tracks_reason():
    cfg = get_polymarket_cli_config()
    scanner = CLIMarketScanner(config=cfg, cli=MarketScannerStubCLI([]))

    raw = _valid_market_payload(["1001", "1002"], " with bad datetime")
    raw["endDate"] = "not-a-date"

    parsed = scanner._parse_cli_market(raw, default_symbol="ETH")
    assert parsed is None
    assert scanner._parse_failures["invalid_end_date"] == 1


def test_parse_cli_market_skips_malformed_token_ids_and_tracks_reason():
    cfg = get_polymarket_cli_config()
    scanner = CLIMarketScanner(config=cfg, cli=MarketScannerStubCLI([]))

    raw = _valid_market_payload(["abc", "0xG", "not-a-number"], " with bad tokens")
    raw["endDate"] = int((datetime.utcnow() + timedelta(hours=2)).timestamp())

    parsed = scanner._parse_cli_market(raw, default_symbol="ETH")
    assert parsed is None
    assert scanner._parse_failures["missing_tokens"] == 1


def test_parse_cli_market_accepts_event_tagged_crypto_market():
    cfg = get_polymarket_cli_config(min_liquidity_usd=1000.0, min_volume_24h_usd=100.0)
    scanner = CLIMarketScanner(config=cfg, cli=MarketScannerStubCLI([]))

    raw = {
        "question": "Will MetaMask launch a token by June 30?",
        "description": "Token launch prediction market.",
        "slug": "will-metamask-launch-a-token-by-june-30",
        "clobTokenIds": ["1001", "1002"],
        "outcomePrices": [0.41, 0.59],
        "liquidityNum": 12000.0,
        "volumeNum": 180.0,
        "active": True,
        "acceptingOrders": True,
        "endDate": int((datetime.utcnow() + timedelta(hours=6)).timestamp()),
        "eventTitle": "Will MetaMask launch a token by ___ ?",
        "eventTags": [{"slug": "crypto", "label": "Crypto"}],
    }

    parsed = scanner._parse_cli_market(raw, default_symbol="ETH")

    assert parsed is not None
    assert parsed.liquidity == 12000.0
    assert parsed.volume_24h == 180.0
    assert parsed.symbol == "CRYPTO"


def test_scan_markets_dedupe_stable_under_token_reversal():
    cfg = get_polymarket_cli_config(min_liquidity_usd=1, min_volume_24h_usd=1)
    payloads = [
        _valid_market_payload(["101", "202"], " A"),
        _valid_market_payload(["202", "101"], " B"),
    ]
    scanner = CLIMarketScanner(config=cfg, cli=MarketScannerStubCLI(payloads))

    markets = scanner.scan_markets(force_refresh=True)

    assert len(markets) == 1
    assert scanner._parse_failures["duplicate_key"] >= 1
    assert scanner.last_scan_stats["tradeable"] == 1


def test_scan_markets_enforces_configured_symbol_universe():
    cfg = get_polymarket_cli_config(
        search_symbols=["ETH"],
        min_liquidity_usd=1,
        min_volume_24h_usd=1,
    )
    payloads = [
        {
            **_valid_market_payload(["101", "202"], " ETH"),
            "question": "ETH above 3000 by tomorrow",
        },
        {
            **_valid_market_payload(["303", "404"], " BTC"),
            "question": "BTC above 100000 by tomorrow",
        },
    ]
    scanner = CLIMarketScanner(config=cfg, cli=MarketScannerStubCLI(payloads))

    markets = scanner.scan_markets(force_refresh=True)

    assert len(markets) == 1
    assert markets[0].symbol == "ETH"
    assert scanner._parse_failures["symbol_filtered"] >= 1


def test_market_dedupe_key_canonicalization_and_fallback():
    cfg = get_polymarket_cli_config()
    scanner = CLIMarketScanner(config=cfg, cli=MarketScannerStubCLI([]))

    market_a = CLIMarket(
        condition_id="200:100",
        question="ETH up or down above 1000",
        symbol="ETH",
        yes_token_id="100",
        no_token_id="200",
        yes_price=0.5,
        no_price=0.5,
        liquidity=1000,
        volume_24h=5000,
        end_date=None,
    )

    market_b = CLIMarket(
        condition_id="100:200",
        question="ETH up or down below 800",
        symbol="ETH",
        yes_token_id="200",
        no_token_id="100",
        yes_price=0.5,
        no_price=0.5,
        liquidity=1000,
        volume_24h=5000,
        end_date=None,
    )
    market_c = CLIMarket(
        condition_id="",
        question="ETH event two-token pair",
        symbol="ETH",
        yes_token_id="",
        no_token_id="",
        yes_price=0.5,
        no_price=0.5,
        liquidity=1000,
        volume_24h=5000,
        end_date=None,
        slug="event-slug",
    )

    assert scanner._market_dedupe_key(market_a, {}) == "cond:100:200"
    assert scanner._market_dedupe_key(market_b, {}) == "cond:100:200"
    assert scanner._market_dedupe_key(market_c, {"slug": "event-slug"}) == "slug:event-slug"


def test_market_dedupe_key_symbol_and_question_fallback():
    cfg = get_polymarket_cli_config()
    scanner = CLIMarketScanner(config=cfg, cli=MarketScannerStubCLI([]))

    market_eth = CLIMarket(
        condition_id="",
        question="Crypto market question with overlap",
        symbol="ETH",
        yes_token_id="",
        no_token_id="",
        yes_price=0.45,
        no_price=0.55,
        liquidity=1000,
        volume_24h=5000,
        end_date=None,
        is_active=True,
        market_type="neutral",
        duration_minutes=None,
        slug="",
    )
    market_sol = CLIMarket(
        condition_id="",
        question="Crypto market question with overlap",
        symbol="SOL",
        yes_token_id="",
        no_token_id="",
        yes_price=0.45,
        no_price=0.55,
        liquidity=1000,
        volume_24h=5000,
        end_date=None,
        is_active=True,
        market_type="neutral",
        duration_minutes=None,
        slug="",
    )

    eth_key = scanner._market_dedupe_key(market_eth, {})
    sol_key = scanner._market_dedupe_key(market_sol, {})

    assert eth_key == "sym:ETH:crypto market question with overlap"
    assert sol_key == "sym:SOL:crypto market question with overlap"
    assert eth_key != sol_key


def test_is_crypto_market_uses_event_metadata_tags():
    cfg = get_polymarket_cli_config()
    scanner = CLIMarketScanner(config=cfg, cli=MarketScannerStubCLI([]))

    assert scanner._is_crypto_market(
        "Will MetaMask launch a token by June 30?",
        {
            "question": "Will MetaMask launch a token by June 30?",
            "eventTitle": "Will MetaMask launch a token by ___ ?",
            "eventTags": [{"slug": "crypto", "label": "Crypto"}],
        },
    ) is True


def test_parse_cli_market_accepts_weather_tagged_market():
    cfg = get_polymarket_cli_config(
        market_vertical="weather",
        min_liquidity_usd=100.0,
        min_volume_24h_usd=0.0,
        max_expiry_hours=72.0,
        min_expiry_minutes=0.0,
    )
    scanner = CLIMarketScanner(config=cfg, cli=MarketScannerStubCLI([]))

    raw = {
        "question": "Will NYC high temperature be above 75F on May 5?",
        "description": "This weather market resolves from official observations.",
        "slug": "nyc-high-temperature-above-75f-may-5",
        "clobTokenIds": ["5001", "5002"],
        "outcomePrices": [0.44, 0.56],
        "liquidityNum": 1200.0,
        "volumeNum": 10.0,
        "active": True,
        "acceptingOrders": True,
        "endDate": int((datetime.utcnow() + timedelta(hours=48)).timestamp()),
        "eventTags": [{"slug": "weather", "label": "Weather"}],
    }

    parsed = scanner._parse_cli_market(raw, default_symbol="WEATHER")

    assert parsed is not None
    assert parsed.symbol == "WEATHER"
    assert parsed.market_type == "bullish"
    assert parsed.price_target == 75.0


def test_weather_scan_includes_weather_tagged_gamma_events():
    cfg = get_polymarket_cli_config(
        market_vertical="weather",
        search_symbols=["WEATHER"],
        min_liquidity_usd=100.0,
        min_volume_24h_usd=0.0,
        max_expiry_hours=72.0,
        min_expiry_minutes=0.0,
    )
    scanner = CLIMarketScanner(config=cfg, cli=WeatherTagScannerStubCLI([]))

    markets = scanner.scan_markets(force_refresh=True)

    assert [market.condition_id for market in markets] == ["weather-tag-1"]
    assert scanner.last_scan_telemetry["tradeable"] == 1


def test_weather_vertical_rejects_crypto_market():
    cfg = get_polymarket_cli_config(market_vertical="weather")
    scanner = CLIMarketScanner(config=cfg, cli=MarketScannerStubCLI([]))
    raw = _valid_market_payload(["9001", "9002"], " crypto")
    raw["question"] = "Will ETH be above 3000 tomorrow?"

    parsed = scanner._parse_cli_market(raw, default_symbol="WEATHER")

    assert parsed is None
    assert scanner._parse_failures["non_weather_question"] == 1
