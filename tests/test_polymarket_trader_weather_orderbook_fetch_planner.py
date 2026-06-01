from datetime import datetime, timedelta

from src.agents.polymarket_trader.models import CLIMarket
from src.agents.polymarket_trader.weather_market_universe_router import WeatherRoutedMarket
from src.agents.polymarket_trader.weather_orderbook_fetch_planner import WeatherOrderbookFetchPlanner


NOW = datetime(2026, 5, 8, 18, 0, 0)


def _market(market_id, question, yes=0.45, no=0.55, liquidity=1000.0):
    return CLIMarket(
        condition_id=market_id,
        question=question,
        symbol="WEATHER",
        yes_token_id=f"yes-{market_id}",
        no_token_id=f"no-{market_id}",
        yes_price=yes,
        no_price=no,
        liquidity=liquidity,
        volume_24h=100.0,
        end_date=NOW + timedelta(hours=4),
        event_slug=f"event-{market_id}",
        slug=f"weather-{market_id}",
    )


def _routed(market_id, threshold, liquidity, event_slug):
    return WeatherRoutedMarket(
        market_id=market_id,
        question=f"Weather fixture {market_id}",
        classification={
            "alpha_lanes": ["observation_lag_station_threshold"],
            "event_slug": event_slug,
            "horizon_bucket": "already_in_window",
            "operator": "above",
            "station_id": "KNYC",
            "metric": "temperature_high",
            "threshold": threshold,
            "target_date": "2026-05-08",
            "location_name": "new york city",
        },
        microstructure={"liquidity": liquidity, "depth_ok": False},
        research_score=80.0,
        route_reasons=[],
    )


def test_observation_lag_planner_prioritizes_proved_threshold_over_liquidity():
    known = _routed("known", 85.0, 500.0, "known-event")
    unproved = _routed("unproved", 120.0, 50000.0, "unproved-event")
    markets = {
        "known": _market("known", "Will the high temperature in New York City exceed 85°F on May 8?", yes=0.40),
        "unproved": _market(
            "unproved",
            "Will the high temperature in New York City exceed 120°F on May 8?",
            yes=0.10,
            liquidity=50000.0,
        ),
    }
    station_states = {
        "KNYC": {
            "station_id": "KNYC",
            "observation_count": 1,
            "observed_max_temp_f": 90.0,
            "latest_observation_age_seconds": 300.0,
            "blockers": [],
        }
    }

    plan = WeatherOrderbookFetchPlanner().plan_observation_lag(
        [unproved, known],
        station_states=station_states,
        market_by_id=markets,
        orderbook_limit=1,
        per_group_limit=1,
        now=NOW,
    )

    assert plan.selected_market_ids == ["known"]
    selected = plan.selected_jobs[0].to_dict()
    assert selected["priority"] == "P0_known_outcome_observation_lag"
    assert selected["metadata"]["expected_side"] == "YES"
    assert selected["metadata"]["selected_win_probability"] == 0.985


def test_routed_lane_planner_keeps_priority_waterfall():
    obs = _routed("obs", 85.0, 1000.0, "obs-event")
    ladder = WeatherRoutedMarket(
        market_id="ladder",
        question="Weather ladder fixture",
        classification={
            "alpha_lanes": ["ladder_consistency"],
            "event_slug": "ladder-event",
            "horizon_bucket": "6_24h",
        },
        microstructure={"liquidity": 100000.0},
        research_score=90.0,
        route_reasons=[],
    )

    plan = WeatherOrderbookFetchPlanner().plan_routed_lane_jobs([ladder, obs], orderbook_limit=2)

    assert plan.selected_market_ids == ["obs", "ladder"]
    assert plan.to_dict()["selected_priority_counts"] == {
        "P0_observation_lag_precheck": 1,
        "P1_ladder_consistency": 1,
    }
