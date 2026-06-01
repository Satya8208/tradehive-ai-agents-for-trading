from src.agents.polymarket_trader.weather_fillability_report import (
    WEATHER_FILLABILITY_REPORT_SCHEMA_VERSION,
    WeatherFillabilityReporter,
)


def test_weather_fillability_report_summarizes_walked_book_capacity():
    report = WeatherFillabilityReporter().build(
        [
            {
                "market_id": "m1",
                "status": "candidate",
                "side": "YES",
                "generated_at": "2026-05-08T10:00:02",
                "edge_after_cost": 0.12,
                "fill_simulation": {
                    "side": "YES",
                    "status": "full",
                    "requested_size_usd": 5.0,
                    "filled_notional_usd": 5.0,
                    "fill_ratio": 1.0,
                    "average_price": 0.40,
                    "best_price": 0.39,
                    "worst_price": 0.41,
                    "total_depth_usd_at_limit": 12.0,
                    "level_count_available": 2,
                    "level_count_consumed": 2,
                    "price_source": "orderbook_best_ask",
                    "blockers": [],
                },
                "blockers": [],
            },
            {
                "market_id": "m2",
                "status": "blocked",
                "side": "NO",
                "edge_after_cost": None,
                "fill_simulation": {
                    "side": "NO",
                    "status": "no_depth",
                    "requested_size_usd": 5.0,
                    "filled_notional_usd": 0.0,
                    "fill_ratio": 0.0,
                    "price_source": "missing",
                    "blockers": ["fill_orderbook_empty"],
                },
                "blockers": ["executable_fill_below_minimum"],
            },
        ],
        tape_by_market={
            "m1": {
                "captured_at": "2026-05-08T10:00:00",
                "yes_book": {"ask_levels": [{"price": 0.39, "size": 10}]},
            }
        },
        generated_at="2026-05-08T10:00:03",
    )

    assert report["schema_version"] == WEATHER_FILLABILITY_REPORT_SCHEMA_VERSION
    assert report["candidate_count"] == 2
    assert report["paper_candidate_count"] == 1
    assert report["full_fill_positive_edge_count"] == 1
    assert report["positive_edge_capacity_usd"] == 5.0
    assert report["by_fill_status"] == {"full": 1, "no_depth": 1}
    assert report["top_rows"][0]["book_age_seconds"] == 2.0
    assert report["top_rows"][0]["book_fingerprint"]
    assert report["blocker_summary"]["by_category"]["execution_microstructure"] >= 1
