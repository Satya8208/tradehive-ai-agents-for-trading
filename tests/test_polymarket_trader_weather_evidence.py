import json
from datetime import datetime, timedelta

from src.agents.polymarket_trader.config import ExecutionMode, get_polymarket_cli_config
from src.agents.polymarket_trader.models import CLIMarket, TradeDecision
from src.agents.polymarket_trader.orchestrator import PolymarketCLIOrchestrator
from src.agents.polymarket_trader.weather_contracts import FEATURE_SCHEMA_VERSION
from src.agents.polymarket_trader.weather_evidence_store import WeatherEvidenceStore
from src.agents.polymarket_trader.weather_market_tape import WeatherMarketTapeCollector
from src.agents.polymarket_trader.weather_replay import WeatherReplayEngine
from src.agents.polymarket_trader.weather_resolution_labels import WeatherResolutionLabelCollector, WeatherResolutionLabeler


def _weather_market():
    return CLIMarket(
        condition_id="weather-evidence-1",
        question="Will NYC high temperature be above 75F on May 3?",
        symbol="WEATHER",
        yes_token_id="yes-token",
        no_token_id="no-token",
        yes_price=0.45,
        no_price=0.55,
        liquidity=1000.0,
        volume_24h=100.0,
        end_date=datetime.utcnow() + timedelta(hours=8),
        is_active=True,
        slug="nyc-high-temp-75",
    )


class _BookCLI:
    def get_order_book(self, token_id):
        if token_id == "yes-token":
            return {
                "bids": [{"price": "0.44", "size": "100"}],
                "asks": [{"price": "0.46", "size": "80"}],
            }
        return {
            "bids": [{"price": "0.53", "size": "60"}],
            "asks": [{"price": "0.56", "size": "50"}],
        }


class _LabelSession:
    def get(self, url, params=None, timeout=None):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "conditionId": "weather-evidence-1",
                    "question": "Will NYC high temperature be above 75F?",
                    "outcomes": '["Yes", "No"]',
                    "outcomePrices": '["1", "0"]',
                    "closed": True,
                }

        return Response()


def _clean_context(market):
    return {
        market.condition_id: {
            "status": "ok",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "selected_source_id": "open_meteo_forecast",
            "selected_source_family": "open_meteo",
            "weather_probability": 0.80,
            "weather_confidence": 0.75,
            "weather_edge_percent": 35.0,
            "recommended_side": "YES",
            "metric": "temperature_high",
            "threshold": 75.0,
            "target_date": "2026-05-03",
            "station_mapping": {"location_name": "New York City", "resolution_station": "KNYC"},
            "source_statuses": {"station_mapper": "ok", "open_meteo_forecast": "live_safe"},
            "forecast_snapshots": [{"source_id": "open_meteo_forecast", "status": "live_safe"}],
            "market_spec": {"market_id": market.condition_id, "resolution_station": "KNYC"},
            "evidence_refs": {"market_id": market.condition_id, "forecast_source_ids": ["open_meteo_forecast"]},
            "asof_time": "2026-05-03T12:00:00",
            "edge_reason_flags": ["calibration_edge"],
            "quality_flags": [],
        }
    }


def test_market_tape_collector_records_orderbook_executable_prices(tmp_path):
    cfg = get_polymarket_cli_config(
        market_vertical="weather",
        weather_market_tape_fetch_orderbook=True,
        _data_dir_override=tmp_path / "pm_tape",
    )
    snapshot = WeatherMarketTapeCollector(cfg, _BookCLI()).snapshot_market(_weather_market())

    assert snapshot.schema_version == "weather_market_tape_v1"
    assert snapshot.executable_yes_price == 0.46
    assert snapshot.executable_no_price == 0.56
    assert snapshot.yes_book["status"] == "ok"
    assert snapshot.yes_book["ask_depth_usd"] == 36.8
    assert snapshot.executable_price_source == "orderbook_best_ask"
    assert snapshot.executable_yes_price_source == "orderbook_best_ask"
    assert snapshot.executable_no_price_source == "orderbook_best_ask"


def test_resolution_labeler_only_accepts_unambiguous_outcome_prices():
    labeler = WeatherResolutionLabeler()

    resolved = labeler.label_from_gamma_market(
        {
            "conditionId": "weather-label-1",
            "question": "Will NYC high temperature be above 75F?",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["1", "0"]',
            "closed": True,
        }
    )
    ambiguous = labeler.label_from_gamma_market(
        {
            "conditionId": "weather-label-2",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.55", "0.45"]',
            "closed": True,
        }
    )
    active_near_terminal = labeler.label_from_gamma_market(
        {
            "conditionId": "weather-label-3",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.99", "0.01"]',
            "active": True,
            "closed": False,
        }
    )
    winner_field = labeler.label_from_gamma_market(
        {
            "conditionId": "weather-label-4",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.55", "0.45"]',
            "winningOutcome": "No",
            "closed": True,
        },
        source_metadata={"evidence_sources": ["replay_records"]},
    )

    assert resolved.label_status == "resolved"
    assert resolved.yes_resolved is True
    assert ambiguous.label_status == "ambiguous"
    assert "resolution_outcome_price_ambiguous" in ambiguous.blockers
    assert active_near_terminal.label_status == "pending"
    assert "resolution_market_not_closed" in active_near_terminal.blockers
    assert winner_field.label_status == "resolved"
    assert winner_field.yes_resolved is False
    assert winner_field.source == "polymarket_winner_field"
    assert winner_field.source_metadata["evidence_sources"] == ["replay_records"]


def test_weather_replay_generates_accepted_evidence_report(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        weather_market_tape_fetch_orderbook=True,
        _data_dir_override=tmp_path / "pm_replay",
    )
    store = WeatherEvidenceStore(cfg)
    market = _weather_market()
    tape = WeatherMarketTapeCollector(cfg, _BookCLI()).snapshot_market(market)
    store.append_market_tape([tape], cycle=1)
    store.append_feature_snapshots([market], _clean_context(market), cycle=1, captured_at=tape.captured_at)
    feature_row = store.read_feature_snapshots()[0]
    assert feature_row["market_spec"]["resolution_station"] == "KNYC"
    assert feature_row["evidence_refs"]["forecast_source_ids"] == ["open_meteo_forecast"]
    assert feature_row["asof_time"] == "2026-05-03T12:00:00"
    store.append_candidate_events(
        [
            {
                "market_id": market.condition_id,
                "accepted": True,
                "reason": "ok",
                "source": "weather_gate",
                "candidate": {
                    "market_id": market.condition_id,
                    "side": "YES",
                    "model_probability": 0.80,
                    "market_probability": 0.45,
                    "edge_percent": 35.0,
                    "confidence": 0.75,
                    "size_usd": 10.0,
                    "limit_price": 0.45,
                    "blockers": [],
                    "edge_reason_flags": ["calibration_edge"],
                    "quality_flags": [],
                },
                "verdict": {"accepted": True, "blockers": [], "reason": "ok"},
                "final_trade_status": "executed",
                "final_trade_side": "YES",
                "final_trade_price": 0.46,
                "final_trade_size_usd": 10.0,
            }
        ],
        cycle=1,
        captured_at=tape.captured_at,
    )
    label = WeatherResolutionLabeler().label_from_gamma_market(
        {
            "conditionId": market.condition_id,
            "question": market.question,
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["1", "0"]',
            "closed": True,
        },
        captured_at=tape.captured_at,
    )
    store.append_resolution_labels([label.to_dict()])

    report = WeatherReplayEngine(cfg, store).write_replay_and_report(
        min_resolved_markets=1,
        min_trade_decisions=1,
    )

    assert report["resolved_record_count"] == 1
    assert report["tradeable_replay_count"] == 1
    assert report["candidate_roi_per_1usd"] > 0
    assert report["model_brier"] < report["market_brier"]
    assert report["event_time_integrity"]["passed"] is True
    assert report["deployment_verdict"]["accepted_for_paper_weather_trading"] is True
    assert report["deployment_verdict"]["accepted_for_live_weather_trading"] is False
    assert "weather_live_requires_preflight_and_manual_enablement" in report["deployment_verdict"]["live_blockers"]
    assert store.replay_records_path.exists()
    assert store.latest_report_markdown_path.exists()


def test_weather_replay_scores_final_trade_side_not_gate_candidate(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        weather_market_tape_fetch_orderbook=True,
        _data_dir_override=tmp_path / "pm_replay_final_side",
    )
    store = WeatherEvidenceStore(cfg)
    market = _weather_market()
    tape = WeatherMarketTapeCollector(cfg, _BookCLI()).snapshot_market(market)
    store.append_market_tape([tape], cycle=1)
    store.append_feature_snapshots([market], _clean_context(market), cycle=1, captured_at=tape.captured_at)
    store.append_candidate_events(
        [
            {
                "market_id": market.condition_id,
                "accepted": True,
                "candidate": {
                    "market_id": market.condition_id,
                    "side": "YES",
                    "model_probability": 0.20,
                    "market_probability": 0.45,
                    "edge_percent": -25.0,
                    "size_usd": 10.0,
                    "blockers": [],
                },
                "verdict": {"accepted": True, "blockers": [], "reason": "ok"},
                "final_trade_status": "executed",
                "final_trade_side": "NO",
                "final_trade_price": 0.56,
                "final_trade_size_usd": 10.0,
            }
        ],
        cycle=1,
        captured_at=tape.captured_at,
    )
    label = WeatherResolutionLabeler().label_from_gamma_market(
        {
            "conditionId": market.condition_id,
            "question": market.question,
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0", "1"]',
            "closed": True,
        },
        captured_at=tape.captured_at,
    )
    store.append_resolution_labels([label.to_dict()])

    report = WeatherReplayEngine(cfg, store).write_replay_and_report(
        min_resolved_markets=1,
        min_trade_decisions=1,
    )
    replay_record = store.read_jsonl(store.replay_records_path)[0]

    assert replay_record["side"] == "NO"
    assert replay_record["selected_win"] is True
    assert replay_record["executable_price"] == 0.56
    assert replay_record["event_time_checks"]["market_tape_at_or_before_decision"] is True
    assert report["tradeable_replay_count"] == 1


def test_weather_resolution_label_collector_reads_evidence_and_writes_summary(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        _data_dir_override=tmp_path / "pm_label_collect",
    )
    store = WeatherEvidenceStore(cfg)
    market = _weather_market()
    tape = WeatherMarketTapeCollector(cfg).snapshot_market(market)
    store.append_market_tape([tape], cycle=1)

    summary = WeatherResolutionLabelCollector(cfg, store=store, session=_LabelSession()).collect(limit=10)
    labels = store.read_resolution_labels()

    assert summary["labels_written"] == 1
    assert summary["by_label_status"]["resolved"] == 1
    assert summary["by_evidence_source"]["market_tape"] == 1
    assert labels[0]["yes_resolved"] is True
    assert labels[0]["source_metadata"]["matched_by"]
    assert labels[0]["source_metadata"]["evidence_sources"] == ["market_tape"]
    assert (store.root_dir / "label_collection_summary.json").exists()


def test_weather_replay_refuses_future_only_market_tape(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        _data_dir_override=tmp_path / "pm_replay_future_tape",
    )
    store = WeatherEvidenceStore(cfg)
    market = _weather_market()
    decision_at = datetime(2026, 5, 3, 10, 0, 0)
    tape_at = datetime(2026, 5, 3, 10, 5, 0)
    tape = WeatherMarketTapeCollector(cfg).snapshot_market(market, captured_at=tape_at)
    store.append_market_tape([tape], cycle=1)
    store.append_feature_snapshots(
        [market],
        _clean_context(market),
        cycle=1,
        captured_at=tape.captured_at,
    )
    store.append_candidate_events(
        [
            {
                "market_id": market.condition_id,
                "captured_at": decision_at.isoformat(),
                "accepted": True,
                "candidate": {
                    "market_id": market.condition_id,
                    "side": "YES",
                    "model_probability": 0.80,
                    "market_probability": 0.45,
                    "edge_percent": 35.0,
                    "size_usd": 10.0,
                    "blockers": [],
                },
                "verdict": {"accepted": True, "blockers": [], "reason": "ok"},
            }
        ],
        cycle=1,
    )
    label = WeatherResolutionLabeler().label_from_gamma_market(
        {
            "conditionId": market.condition_id,
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["1", "0"]',
            "closed": True,
        },
        captured_at=tape.captured_at,
    )
    store.append_resolution_labels([label.to_dict()])

    report = WeatherReplayEngine(cfg, store).write_replay_and_report(
        min_resolved_markets=1,
        min_trade_decisions=1,
    )
    replay_record = store.read_jsonl(store.replay_records_path)[0]

    assert report["tradeable_replay_count"] == 0
    assert report["event_time_integrity"]["market_tape_after_decision_count"] == 0
    assert report["deployment_verdict"]["accepted_for_paper_weather_trading"] is False
    assert "replay_market_tape_missing" in replay_record["blockers"]
    assert replay_record["snapshot_time"] == ""


def test_weather_orchestrator_writes_evidence_artifacts(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        search_symbols=["WEATHER"],
        cycle_interval_seconds=0,
        max_markets_to_analyze=1,
        min_liquidity_usd=100.0,
        min_edge_threshold=1.0,
        _data_dir_override=tmp_path / "pm_orch_evidence",
    )
    orchestrator = PolymarketCLIOrchestrator(cfg)
    market = _weather_market()

    orchestrator.scanner.scan_markets = lambda force_refresh=False: [market]
    orchestrator.scanner.rank_markets = lambda markets: [(m, 1.0) for m in markets]
    orchestrator.signals.get_market_context = lambda markets: _clean_context(markets[0])
    orchestrator.whale_tracker.scan_whales = lambda: []
    orchestrator.risk_manager.refresh_position_prices = lambda _cli: {}
    orchestrator.risk_manager.check_resolved_markets = lambda _cli: []
    orchestrator.arbitrage_detector.detect_all = lambda _markets: []
    orchestrator._should_scan_whales = lambda: False
    orchestrator.analyzer.analyze_market = (
        lambda *_args, **_kwargs: type(
            "FakeConsensus",
            (),
            {
                "consensus_prediction": "YES",
                "consensus_probability": 0.80,
                "consensus_confidence": 0.75,
                "analysis_path": "",
            },
        )()
    )

    summary = orchestrator.run(cycles=1)[0]
    evidence_dir = cfg.data_dir / "weather_evidence"

    assert summary["status"] == "complete"
    assert summary["weather_evidence"]["status"] == "recorded"
    assert summary["weather_evidence"]["market_tape_count"] == 1
    assert (evidence_dir / "market_tape.jsonl").exists()
    assert (evidence_dir / "feature_snapshots.jsonl").exists()
    assert (evidence_dir / "candidate_decisions.jsonl").exists()
    tape = json.loads((evidence_dir / "market_tape.jsonl").read_text().splitlines()[0])
    candidate = json.loads((evidence_dir / "candidate_decisions.jsonl").read_text().splitlines()[0])
    assert candidate["accepted"] is True
    assert candidate["final_trade_status"] in {"planned", "executed", "skipped"}
    assert tape["captured_at"] <= candidate["captured_at"]


def test_live_weather_execution_is_globally_blocked_even_for_arbitrage(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.LIVE,
        market_vertical="weather",
        _data_dir_override=tmp_path / "pm_weather_live_block",
    )
    orchestrator = PolymarketCLIOrchestrator(cfg)
    market = _weather_market()
    decision = TradeDecision(
        market_id=market.condition_id,
        timestamp=datetime.utcnow(),
        should_trade=True,
        side="YES",
        size_usd=5.0,
        price=0.46,
        confidence=0.75,
        reason="fixture arbitrage",
        source="arbitrage",
    )

    ledger = orchestrator._execute_cycle_plan([(decision, market, "arbitrage")], {"cycle": 1})

    assert ledger["executed"] == []
    assert ledger["planned"] == []
    assert ledger["blocked"][0]["reason"] == "WEATHER_LIVE_ELIGIBILITY_FAILED"
    assert "allow_live_weather_trading_false" in ledger["blocked"][0]["detail"]
