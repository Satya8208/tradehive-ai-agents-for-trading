from datetime import datetime, timedelta

from src.agents.polymarket_trader.arbitrage_detector import ArbitrageDetector
from src.agents.polymarket_trader.config import get_polymarket_cli_config
from src.agents.polymarket_trader.models import CLIMarket


def _arb_market(**overrides):
    base = dict(
        condition_id="arb-1",
        question="ETH above $3000 by tomorrow",
        symbol="ETH",
        yes_token_id="1",
        no_token_id="2",
        yes_price=0.52,
        no_price=0.48,
        liquidity=50000.0,
        volume_24h=25000.0,
        end_date=datetime.utcnow() + timedelta(hours=4),
        is_active=True,
        market_type="bullish",
        price_target=3000.0,
        spread=0.02,
    )
    base.update(overrides)
    return CLIMarket(**base)


def test_complementary_arbs_require_quality_and_strict_edge(tmp_path):
    cfg = get_polymarket_cli_config(
        min_arb_edge_percent=0.3,
        min_liquidity_usd=1000.0,
        min_volume_24h_usd=1000.0,
        _data_dir_override=tmp_path / "arb_quality",
    )
    detector = ArbitrageDetector(config=cfg)

    good_above = _arb_market(
        condition_id="good-above",
        question="ETH above $3000 by tomorrow",
        market_type="bullish",
        yes_price=0.39,
        no_price=0.61,
        price_target=3000.0,
        liquidity=50000.0,
        volume_24h=20000.0,
    )
    good_below = _arb_market(
        condition_id="good-below",
        question="ETH below $3000 by tomorrow",
        market_type="bearish",
        yes_price=0.64,
        no_price=0.36,
        price_target=3000.0,
        liquidity=50000.0,
        volume_24h=20000.0,
    )
    weak_above = _arb_market(
        condition_id="weak-above",
        question="ETH above $3100 by tomorrow",
        market_type="bullish",
        yes_price=0.40,
        no_price=0.60,
        price_target=3100.0,
        liquidity=50000.0,
        volume_24h=500.0,
    )
    weak_below = _arb_market(
        condition_id="weak-below",
        question="ETH below $3100 by tomorrow",
        market_type="bearish",
        yes_price=0.63,
        no_price=0.37,
        price_target=3100.0,
        liquidity=50000.0,
        volume_24h=500.0,
    )

    opportunities = detector.detect_complementary_arbs([good_above, good_below, weak_above, weak_below])

    assert len(opportunities) == 1
    assert opportunities[0].markets[0].condition_id in {"good-above", "good-below"}
    assert opportunities[0].markets[1].condition_id in {"good-above", "good-below"}


def test_range_sum_arbs_require_three_clean_markets(tmp_path):
    cfg = get_polymarket_cli_config(
        min_arb_edge_percent=0.3,
        min_liquidity_usd=1000.0,
        min_volume_24h_usd=1000.0,
        _data_dir_override=tmp_path / "arb_range",
    )
    detector = ArbitrageDetector(config=cfg)

    markets = [
        CLIMarket(
            condition_id="range-1",
            question="Bitcoin between $90k-$95k by Friday",
            symbol="BTC",
            yes_token_id="11",
            no_token_id="12",
            yes_price=0.41,
            no_price=0.59,
            liquidity=50000.0,
            volume_24h=20000.0,
            end_date=datetime.utcnow() + timedelta(hours=8),
            is_active=True,
            market_type="neutral",
            spread=0.02,
        ),
        CLIMarket(
            condition_id="range-2",
            question="Bitcoin between $95k-$100k by Friday",
            symbol="BTC",
            yes_token_id="13",
            no_token_id="14",
            yes_price=0.39,
            no_price=0.61,
            liquidity=50000.0,
            volume_24h=20000.0,
            end_date=datetime.utcnow() + timedelta(hours=8),
            is_active=True,
            market_type="neutral",
            spread=0.02,
        ),
    ]

    assert detector.detect_range_sum_arbs(markets) == []


def _weather_bucket(condition_id, question, yes_price, no_price):
    return CLIMarket(
        condition_id=condition_id,
        question=question,
        symbol="WEATHER",
        yes_token_id=f"{condition_id}-yes",
        no_token_id=f"{condition_id}-no",
        yes_price=yes_price,
        no_price=no_price,
        liquidity=50000.0,
        volume_24h=20000.0,
        end_date=datetime.utcnow() + timedelta(hours=8),
        is_active=True,
        market_type="neutral",
        spread=0.02,
    )


def test_weather_range_no_basket_uses_all_exclusive_buckets(tmp_path):
    cfg = get_polymarket_cli_config(
        market_vertical="weather",
        min_arb_edge_percent=1.0,
        arb_fee_estimate_percent=0.0,
        min_liquidity_usd=1000.0,
        min_volume_24h_usd=1000.0,
        _data_dir_override=tmp_path / "weather_range_no",
    )
    detector = ArbitrageDetector(config=cfg)
    markets = [
        _weather_bucket(
            "sf-60",
            "Will the highest temperature in San Francisco be between 60-61°F on May 2?",
            0.44,
            0.56,
        ),
        _weather_bucket(
            "sf-62",
            "Will the highest temperature in San Francisco be between 62-63°F on May 2?",
            0.43,
            0.57,
        ),
        _weather_bucket(
            "sf-64",
            "Will the highest temperature in San Francisco be between 64-65°F on May 2?",
            0.42,
            0.58,
        ),
    ]

    opportunities = detector.detect_all(markets)

    assert len(opportunities) == 1
    assert opportunities[0].arb_type == "weather_range_no_basket"
    assert round(opportunities[0].edge_percent, 2) == 29.0
    assert len(opportunities[0].recommended_trades) == 3
    assert {trade["side"] for trade in opportunities[0].recommended_trades} == {"NO"}
    target_shares = {trade["target_shares"] for trade in opportunities[0].recommended_trades}
    assert len(target_shares) == 1
    for trade in opportunities[0].recommended_trades:
        assert abs((trade["size_usd"] / trade["price"]) - trade["target_shares"]) < 0.001


def test_weather_range_no_basket_does_not_mix_locations_or_buy_underpriced_yes(tmp_path):
    cfg = get_polymarket_cli_config(
        market_vertical="weather",
        min_arb_edge_percent=1.0,
        arb_fee_estimate_percent=0.0,
        min_liquidity_usd=1000.0,
        min_volume_24h_usd=1000.0,
        _data_dir_override=tmp_path / "weather_range_grouping",
    )
    detector = ArbitrageDetector(config=cfg)
    markets = [
        _weather_bucket(
            "sf-60",
            "Will the highest temperature in San Francisco be between 60-61°F on May 2?",
            0.34,
            0.66,
        ),
        _weather_bucket(
            "sf-62",
            "Will the highest temperature in San Francisco be between 62-63°F on May 2?",
            0.33,
            0.67,
        ),
        _weather_bucket(
            "mia-90",
            "Will the highest temperature in Miami be between 90-91°F on May 2?",
            0.34,
            0.66,
        ),
    ]

    assert detector.detect_all(markets) == []


def test_weather_range_no_basket_parses_exact_celsius_and_chooses_best_subset(tmp_path):
    cfg = get_polymarket_cli_config(
        market_vertical="weather",
        min_arb_edge_percent=1.0,
        arb_fee_estimate_percent=1.0,
        min_arb_token_price=0.001,
        min_liquidity_usd=1000.0,
        min_volume_24h_usd=1000.0,
        _data_dir_override=tmp_path / "weather_exact_celsius",
    )
    detector = ArbitrageDetector(config=cfg)
    markets = [
        _weather_bucket(
            "hk-21",
            "Will the lowest temperature in Hong Kong be 21°C on May 2?",
            0.39,
            0.61,
        ),
        _weather_bucket(
            "hk-22",
            "Will the lowest temperature in Hong Kong be 22°C on May 2?",
            0.38,
            0.62,
        ),
        _weather_bucket(
            "hk-23",
            "Will the lowest temperature in Hong Kong be 23°C on May 2?",
            0.37,
            0.63,
        ),
        _weather_bucket(
            "hk-tail",
            "Will the lowest temperature in Hong Kong be 28°C on May 2?",
            0.005,
            0.995,
        ),
    ]

    opportunities = detector.detect_all(markets)

    assert len(opportunities) == 1
    traded_ids = {trade["market_id"] for trade in opportunities[0].recommended_trades}
    assert traded_ids == {"hk-21", "hk-22", "hk-23"}
    assert "hk-tail" not in traded_ids
