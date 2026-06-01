from datetime import datetime, timedelta

from src.agents.polymarket_trader.config import get_polymarket_cli_config
from src.agents.polymarket_trader.market_scanner import CLIMarketScanner
from src.agents.polymarket_trader.models import CLIMarket


class QueryAwareScannerCLI:
    def __init__(self):
        self.queries = []

    def search_markets(self, query, limit=50):
        self.queries.append(query)
        q = query.lower()
        if q.endswith("reach") and "eth" in q:
            return [
                {
                    "question": "ETH will reach 3000 with tiny volume",
                    "clobTokenIds": ["101", "102"],
                    "outcomePrices": [0.52, 0.48],
                    "liquidity": 12000.0,
                    "volume24hr": 500.0,
                    "active": True,
                    "acceptingOrders": True,
                    "endDate": int((datetime.utcnow() + timedelta(hours=2)).timestamp()),
                },
                {
                    "question": "ETH will reach 3000 with real volume",
                    "clobTokenIds": ["201", "202"],
                    "outcomePrices": [0.53, 0.47],
                    "liquidity": 15000.0,
                    "volume24hr": 8000.0,
                    "active": True,
                    "acceptingOrders": True,
                    "endDate": int((datetime.utcnow() + timedelta(hours=2)).timestamp()),
                },
            ]
        return []


def test_scan_markets_records_query_telemetry_and_volume_exclusions(tmp_path):
    cfg = get_polymarket_cli_config(
        search_symbols=["ETH", "BTC"],
        min_liquidity_usd=1000.0,
        min_volume_24h_usd=1000.0,
        _data_dir_override=tmp_path / "scanner",
    )
    cli = QueryAwareScannerCLI()
    scanner = CLIMarketScanner(config=cfg, cli=cli)

    markets = scanner.scan_markets(force_refresh=True)

    assert len(markets) == 1
    assert scanner.last_scan_stats["tradeable"] == 1
    assert scanner.last_scan_telemetry["query_count"] == len(cli.queries)
    assert scanner.last_scan_telemetry["query_count"] > len(cfg.crypto_search_queries)
    assert scanner.last_scan_telemetry["filtered"] >= 1
    assert scanner.last_scan_telemetry["no_markets"] is False
    assert scanner._parse_failures["low_volume_24h"] >= 1
    assert any(
        q not in {base_query for base_query, _ in cfg.crypto_search_queries}
        for q in cli.queries
    )


def test_rank_markets_prefers_short_horizon_eth_with_tight_spread(tmp_path):
    cfg = get_polymarket_cli_config(
        search_symbols=["ETH", "BTC"],
        _data_dir_override=tmp_path / "scanner_rank",
    )
    scanner = CLIMarketScanner(config=cfg, cli=QueryAwareScannerCLI())

    now = datetime.utcnow()
    markets = [
        CLIMarket(
            condition_id="eth-fast",
            question="ETH up or down in 1h",
            symbol="ETH",
            yes_token_id="1",
            no_token_id="2",
            yes_price=0.52,
            no_price=0.48,
            liquidity=50000.0,
            volume_24h=20000.0,
            end_date=now + timedelta(hours=1),
            is_active=True,
            market_type="binary_updown",
            duration_minutes=60,
            spread=0.01,
        ),
        CLIMarket(
            condition_id="btc-slow",
            question="BTC above 100k by next week",
            symbol="BTC",
            yes_token_id="3",
            no_token_id="4",
            yes_price=0.71,
            no_price=0.29,
            liquidity=12000.0,
            volume_24h=6000.0,
            end_date=now + timedelta(hours=120),
            is_active=True,
            market_type="bullish",
            price_target=100000.0,
            spread=0.08,
        ),
        CLIMarket(
            condition_id="sol-wide",
            question="SOL above 200 by tomorrow",
            symbol="SOL",
            yes_token_id="5",
            no_token_id="6",
            yes_price=0.61,
            no_price=0.39,
            liquidity=10000.0,
            volume_24h=5000.0,
            end_date=now + timedelta(hours=20),
            is_active=True,
            market_type="bullish",
            price_target=200.0,
            spread=0.10,
        ),
    ]

    ranked = scanner.rank_markets(markets)

    assert ranked[0][0].condition_id == "eth-fast"
    assert ranked[0][1] > ranked[1][1]
    assert ranked[0][1] > ranked[2][1]
