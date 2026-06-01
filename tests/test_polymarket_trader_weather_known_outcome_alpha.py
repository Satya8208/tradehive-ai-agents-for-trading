import json
from datetime import datetime, timedelta

from src.agents.polymarket_trader.config import ExecutionMode, get_polymarket_cli_config
from src.agents.polymarket_trader.models import CLIMarket
from src.agents.polymarket_trader.weather_asos_metar_parser import WeatherASOSMetarParser
from src.agents.polymarket_trader.weather_known_outcome_alpha import (
    KNOWN_OUTCOME_ALPHA_CODE,
    WeatherKnownOutcomeAlpha,
)
from src.agents.polymarket_trader.weather_known_outcome_scan import WeatherKnownOutcomeAlphaScanner
from src.agents.polymarket_trader.weather_market_tape import WeatherMarketTapeCollector
from src.agents.polymarket_trader.weather_market_universe_router import WeatherRoutedMarket
from src.agents.polymarket_trader.weather_observation_ingestor import WeatherObservationIngestor
from src.agents.polymarket_trader.weather_observation_ingestor import WeatherObservationIngestResult
from src.agents.polymarket_trader.weather_station_observation_state import WeatherStationObservationStateBuilder
from src.agents.polymarket_trader.weather_threshold_state import WeatherThresholdStateEvaluator


NOW = datetime(2026, 5, 8, 18, 0, 0)


def _market(question, market_id="known-1", hours=4):
    return CLIMarket(
        condition_id=market_id,
        question=question,
        symbol="WEATHER",
        yes_token_id="yes-token",
        no_token_id="no-token",
        yes_price=0.45,
        no_price=0.55,
        liquidity=2000.0,
        volume_24h=200.0,
        end_date=NOW + timedelta(hours=hours),
        event_slug="nyc-weather",
        slug="nyc-weather-known",
    )


def _tape(yes=0.70, no=0.35):
    return {
        "market_id": "known-1",
        "executable_yes_price": yes,
        "executable_no_price": no,
        "executable_yes_price_source": "orderbook_best_ask",
        "executable_no_price_source": "orderbook_best_ask",
        "executable_price_source": "orderbook_best_ask",
    }


class _MetarSession:
    def get(self, url, params=None, headers=None, timeout=None):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return [
                    {
                        "icaoId": "KNYC",
                        "obsTime": "2026-05-08T17:00:00Z",
                        "rawOb": "KNYC 081700Z 18008KT 10SM FEW050 31/17 A2992",
                        "temp": 31,
                        "wspd": 8,
                    }
                ]

        return Response()


class _Scanner:
    last_scan_telemetry = {"tradeable": 1}

    def __init__(self, markets):
        self.markets = markets

    def scan_markets(self, force_refresh=True):
        return self.markets


class _BookCLI:
    def get_order_book(self, token_id):
        return {
            "bids": [{"price": "0.44", "size": "100"}],
            "asks": [{"price": "0.46", "size": "100"}],
        }


class _ObservationIngestor:
    def fetch_metar_observations(self, station_ids, hours=18):
        obs = WeatherASOSMetarParser().parse_awc_payload(
            [
                {
                    "icaoId": "KNYC",
                    "obsTime": "2026-05-08T17:00:00Z",
                    "rawOb": "KNYC 081700Z 18008KT 10SM FEW050 31/17 A2992",
                    "temp": 31,
                }
            ]
        )
        return WeatherObservationIngestResult(
            station_ids=list(station_ids),
            status="ok",
            observations=[row.to_dict() for row in obs],
            quality_flags=["fixture"],
        )


def test_metar_parser_extracts_temperature_and_wind():
    payload = [
        {
            "icaoId": "KNYC",
            "obsTime": "2026-05-08T17:00:00Z",
            "rawOb": "KNYC 081700Z 18008G18KT 10SM -RA FEW050 31/17 A2992 P0002",
        }
    ]

    obs = WeatherASOSMetarParser().parse_awc_payload(payload)[0]

    assert obs.station_id == "KNYC"
    assert obs.temp_f == 87.8
    assert obs.precipitation_in == 0.02
    assert "-RA" in obs.present_weather


def test_observation_ingestor_uses_awc_metar_payload():
    result = WeatherObservationIngestor(session=_MetarSession()).fetch_metar_observations(["KNYC"], hours=6)

    assert result.status == "ok"
    assert result.station_ids == ["KNYC"]
    assert result.observations[0]["temp_f"] == 87.8
    assert "official_awc_data_api" in result.quality_flags


def test_threshold_state_marks_high_temperature_above_as_known_yes():
    observations = WeatherASOSMetarParser().parse_awc_payload(
        [
            {
                "icaoId": "KNYC",
                "obsTime": "2026-05-08T17:00:00Z",
                "rawOb": "KNYC 081700Z 18008KT 10SM FEW050 31/17 A2992",
                "temp": 31,
            }
        ]
    )
    station_state = WeatherStationObservationStateBuilder().build("KNYC", observations, now=NOW)

    state = WeatherThresholdStateEvaluator().evaluate(
        metric="temperature_high",
        operator="above",
        threshold=85.0,
        station_state=station_state,
        market_end=NOW + timedelta(hours=4),
        now=NOW,
    )

    assert state.status == "known_or_near_known"
    assert state.official_observation_supports_yes is True
    assert state.p_yes == 0.985
    assert state.p_yes_source == "official_observation_fact"
    assert state.probability_role == "settlement_fact"


def test_known_outcome_alpha_emits_executable_yes_candidate():
    observations = WeatherASOSMetarParser().parse_awc_payload(
        [
            {
                "icaoId": "KNYC",
                "obsTime": "2026-05-08T17:00:00Z",
                "rawOb": "KNYC 081700Z 18008KT 10SM FEW050 31/17 A2992",
                "temp": 31,
            }
        ]
    )
    station_state = WeatherStationObservationStateBuilder().build("KNYC", observations, now=NOW)
    market = _market("Will the high temperature in New York City exceed 85°F on May 8?")

    candidate = WeatherKnownOutcomeAlpha().evaluate(market, station_state, tape=_tape(), now=NOW)

    assert candidate.alpha_code == KNOWN_OUTCOME_ALPHA_CODE
    assert candidate.status == "candidate"
    assert candidate.side == "YES"
    assert candidate.p_yes_source == "official_observation_fact"
    assert candidate.probability_role == "settlement_fact"
    assert candidate.edge_after_cost > 0.20
    assert not candidate.blockers


def test_known_outcome_alpha_blocks_non_orderbook_price():
    observations = WeatherASOSMetarParser().parse_awc_payload(
        [
            {
                "icaoId": "KNYC",
                "obsTime": "2026-05-08T17:00:00Z",
                "rawOb": "KNYC 081700Z 18008KT 10SM FEW050 31/17 A2992",
                "temp": 31,
            }
        ]
    )
    station_state = WeatherStationObservationStateBuilder().build("KNYC", observations, now=NOW)
    market = _market("Will the high temperature in New York City exceed 85°F on May 8?")
    tape = _tape()
    tape["executable_yes_price_source"] = "scan_price"

    candidate = WeatherKnownOutcomeAlpha().evaluate(market, station_state, tape=tape, now=NOW)

    assert candidate.status == "blocked"
    assert "executable_price_not_orderbook:scan_price" in candidate.blockers


def test_known_outcome_alpha_detects_high_temperature_below_known_no():
    observations = WeatherASOSMetarParser().parse_awc_payload(
        [
            {
                "icaoId": "KNYC",
                "obsTime": "2026-05-08T17:00:00Z",
                "rawOb": "KNYC 081700Z 18008KT 10SM FEW050 31/17 A2992",
                "temp": 31,
            }
        ]
    )
    station_state = WeatherStationObservationStateBuilder().build("KNYC", observations, now=NOW)
    market = _market("Will the high temperature in New York City be below 85°F on May 8?")

    candidate = WeatherKnownOutcomeAlpha().evaluate(market, station_state, tape=_tape(yes=0.90, no=0.08), now=NOW)

    assert candidate.status == "candidate"
    assert candidate.side == "NO"
    assert candidate.p_yes == 0.015
    assert candidate.selected_win_probability == 0.985


def test_known_outcome_alpha_blocks_dust_depth_candidate():
    observations = WeatherASOSMetarParser().parse_awc_payload(
        [
            {
                "icaoId": "KNYC",
                "obsTime": "2026-05-08T17:00:00Z",
                "rawOb": "KNYC 081700Z 18008KT 10SM FEW050 31/17 A2992",
                "temp": 31,
            }
        ]
    )
    station_state = WeatherStationObservationStateBuilder().build("KNYC", observations, now=NOW)
    market = _market("Will the high temperature in New York City be below 85°F on May 8?")
    tape = _tape(yes=0.90, no=0.08)
    tape["no_book"] = {
        "status": "ok",
        "ask_levels": [{"price": 0.08, "size": 5.0, "notional_usd": 0.4}],
    }

    candidate = WeatherKnownOutcomeAlpha(min_fillable_usd=1.0).evaluate(market, station_state, tape=tape, now=NOW)

    assert candidate.status == "blocked"
    assert candidate.max_fillable_usd == 0.4
    assert "executable_fill_below_minimum" in candidate.blockers


def test_threshold_state_marks_temperature_range_breached_as_known_no():
    observations = WeatherASOSMetarParser().parse_awc_payload(
        [
            {
                "icaoId": "KNYC",
                "obsTime": "2026-05-08T17:00:00Z",
                "rawOb": "KNYC 081700Z 18008KT 10SM FEW050 31/17 A2992",
                "temp": 31,
            }
        ]
    )
    station_state = WeatherStationObservationStateBuilder().build("KNYC", observations, now=NOW)

    state = WeatherThresholdStateEvaluator().evaluate(
        metric="temperature_high",
        operator="between",
        threshold=80.0,
        upper_threshold=85.0,
        station_state=station_state,
        market_end=NOW + timedelta(hours=4),
        now=NOW,
    )

    assert state.status == "known_or_near_known"
    assert state.official_observation_supports_no is True
    assert state.recommended_side == "NO"
    assert state.p_yes == 0.015
    assert state.p_yes_source == "official_observation_fact"


def test_threshold_state_blocks_temperature_range_boundary_rounding_risk():
    state = WeatherThresholdStateEvaluator().evaluate(
        metric="temperature_high",
        operator="between",
        threshold=68.0,
        upper_threshold=69.0,
        station_state={
            "station_id": "KLAX",
            "observation_count": 1,
            "observed_max_temp_f": 69.08,
            "latest_observation_age_seconds": 300.0,
            "blockers": [],
        },
        market_end=NOW + timedelta(hours=4),
        now=NOW,
    )

    assert state.status == "not_known"
    assert state.p_yes is None
    assert "threshold_boundary_rounding_risk" in state.blockers
    assert state.decision_margin == 0.08
    payload = state.to_dict()
    assert payload["blocker_records"][0]["category"] == "threshold_state"
    assert payload["blocker_summary"]["by_owner_role"]["contract_resolution_counsel"] >= 1


def test_known_outcome_alpha_blocks_near_close_heuristic_probability():
    observations = WeatherASOSMetarParser().parse_awc_payload(
        [
            {
                "icaoId": "KNYC",
                "obsTime": "2026-05-08T17:55:00Z",
                "rawOb": "KNYC 081755Z 18008KT 10SM FEW050 27/17 A2992",
                "temp": 27,
            }
        ]
    )
    station_state = WeatherStationObservationStateBuilder().build("KNYC", observations, now=NOW)
    market = _market(
        "Will the high temperature in New York City be below 85Â°F on May 8?",
        hours=0.25,
    )

    candidate = WeatherKnownOutcomeAlpha().evaluate(market, station_state, tape=_tape(yes=0.40, no=0.62), now=NOW)

    assert candidate.status == "blocked"
    assert candidate.p_yes == 0.78
    assert candidate.p_yes_source == "near_close_observation_heuristic"
    assert candidate.probability_role == "heuristic_probability"
    assert candidate.edge_after_cost is None
    assert "known_outcome_probability_not_settlement_fact:near_close_observation_heuristic" in candidate.blockers


def test_known_outcome_scan_writes_research_report(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        _data_dir_override=tmp_path / "pm_known_scan",
        weather_market_tape_fetch_orderbook=True,
    )
    market = _market("Will the high temperature in New York City exceed 85°F on May 8?")
    runner = WeatherKnownOutcomeAlphaScanner(
        config=cfg,
        scanner=_Scanner([market]),
        tape_collector=WeatherMarketTapeCollector(cfg, _BookCLI()),
        observation_ingestor=_ObservationIngestor(),
        output_dir=tmp_path / "known_scan",
    )

    report = runner.run(candidate_limit=5, now=NOW, record_evidence=True)

    assert report["evaluated_candidates"] == 1
    assert report["candidate_count"] == 1
    assert report["observation_eligible_count"] == 1
    assert report["observation_eligibility"]["routed_market_count"] == 1
    assert report["observation_eligibility"]["eligible_count"] == 1
    assert report["observation_eligibility"]["records"][0]["eligible"] is True
    assert report["observation_context"]["destination_counts"]["known_outcome_observation_lag"] == 1
    assert report["candidates"][0]["alpha_code"] == KNOWN_OUTCOME_ALPHA_CODE
    assert report["orderbook_fill_coverage"]["full_fill_count"] == 1
    assert report["fillability_report"]["full_fill_positive_edge_count"] == 1
    assert report["fillability_report"]["positive_edge_capacity_usd"] == 5.0
    assert report["decision_packet_summary"]["decision_packet_count"] == 1
    assert report["decision_packet_summary"]["decision_packets_written"] == 1
    assert report["decision_packet_summary"]["candidate_events_written"] == 1
    assert report["candidate_lifecycle_summary"]["lifecycle_records_written"] == 1
    assert report["candidate_lifecycle_summary"]["by_status"] == {"pending_resolution": 1}
    assert report["observation_selection"]["selected_count"] == 1
    assert report["paper_evidence"]["accepted"][0]["p_yes_source"] == "official_observation_fact"
    assert report["coverage_audit"]["schema_version"] == "weather_coverage_audit_v1"
    assert report["coverage_audit"]["funnel"][1]["stage"] == "router_to_observation_eligible"
    assert report["coverage_audit"]["funnel"][-1]["stage"] == "evaluation_to_accepted_paper"
    evidence_dir = cfg.data_dir / "weather_evidence"
    packet = json.loads((evidence_dir / "decision_packets.jsonl").read_text().splitlines()[0])
    event = json.loads((evidence_dir / "candidate_decisions.jsonl").read_text().splitlines()[0])
    lifecycle = json.loads((evidence_dir / "candidate_lifecycle.jsonl").read_text().splitlines()[0])
    assert packet["status"] == "current_scan_candidate"
    assert packet["evidence_refs"]["orderbook_snapshot_ref"]
    assert event["final_trade_status"] == "planned"
    assert event["decision_packet_id"] == packet["decision_id"]
    assert lifecycle["decision_id"] == packet["decision_id"]
    assert runner.latest_report_path.exists()
    assert runner.latest_report_markdown_path.exists()


def test_known_outcome_scan_spends_book_budget_on_proved_observation(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        _data_dir_override=tmp_path / "pm_known_budget",
        weather_market_tape_fetch_orderbook=True,
    )
    proved = _market(
        "Will the high temperature in New York City exceed 85°F on May 8?",
        market_id="proved",
    )
    unproved = _market(
        "Will the high temperature in New York City exceed 120°F on May 8?",
        market_id="unproved",
    )
    unproved.liquidity = 100000.0
    runner = WeatherKnownOutcomeAlphaScanner(
        config=cfg,
        scanner=_Scanner([unproved, proved]),
        tape_collector=WeatherMarketTapeCollector(cfg, _BookCLI()),
        observation_ingestor=_ObservationIngestor(),
        output_dir=tmp_path / "known_budget_scan",
    )

    report = runner.run(candidate_limit=1, now=NOW)

    assert report["evaluated_candidates"] == 1
    assert report["candidates"][0]["market_id"] == "proved"
    assert report["orderbook_fetch_plan"]["selected_priority_counts"] == {
        "P0_known_outcome_observation_lag": 1,
    }
    assert report["paper_evidence"]["accepted_count"] == 1
    assert report["paper_evidence"]["accepted"][0]["proof"]


def test_observation_lag_selector_diversifies_event_groups():
    def row(market_id, event_slug, liquidity):
        return WeatherRoutedMarket(
            market_id=market_id,
            question=f"Weather fixture {market_id}",
            classification={
                "alpha_lanes": ["observation_lag_station_threshold"],
                "event_slug": event_slug,
                "horizon_bucket": "0_6h",
                "operator": "above",
                "station_id": "KNYC",
                "metric": "temperature_high",
                "target_date": "2026-05-08",
            },
            microstructure={"liquidity": liquidity, "depth_ok": True},
            research_score=100.0,
            route_reasons=[],
        )

    selected = WeatherKnownOutcomeAlphaScanner._observation_lane_rows(
        [
            row("same-1", "same-event", 5000),
            row("same-2", "same-event", 4000),
            row("same-3", "same-event", 3000),
            row("other-1", "other-event", 1000),
            row("third-1", "third-event", 900),
        ],
        limit=3,
        per_group_limit=1,
    )

    assert [item.market_id for item in selected] == ["same-1", "other-1", "third-1"]
