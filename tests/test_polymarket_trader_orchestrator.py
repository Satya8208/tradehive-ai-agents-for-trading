from datetime import datetime, timedelta
import time
import json
from src.agents.polymarket_trader.config import ExecutionMode, get_polymarket_cli_config
from src.agents.polymarket_trader.models import ArbitrageOpportunity, CLIMarket, TradeDecision, TradeExecution
from src.agents.polymarket_trader.orchestrator import PolymarketCLIOrchestrator
from src.agents.polymarket_trader.weather_contracts import FEATURE_SCHEMA_VERSION
from src.agents.polymarket_trader.weather_high_res_cycle import WeatherHighResolutionCycleReport
from src.agents.polymarket_trader.trader import CLITrader


class StubCLI:
    def get_order_book(self, _token_id):
        return None


class StubStatusCLI:
    def __init__(self):
        self._cli_binary = "polymarket-stub"

    def get_health_status(self):
        return {
            "cli_binary": self._cli_binary,
            "cli_available": True,
            "cli_binary_check_error": None,
            "direct_api_available": False,
            "transport": "cli",
            "config_sanity": "ok",
            "config_snapshot": {
                "execution_mode": "dry_run",
                "max_total_exposure_usd": 0.0,
                "max_position_usd": 0.0,
                "min_position_usd": 0.0,
                "cycle_interval_seconds": 60,
                "order_fill_timeout_seconds": 10,
            },
            "errors": [],
            "cli_status_ok": True,
            "wallet_configured": True,
            "wallet_address": "0xdeadbeef",
            "balance_read_ok": True,
            "balance": 123.45,
            "permissions_ok": True,
            "timestamp": time.time(),
        }


def make_market():
    return CLIMarket(
        condition_id="mkt-orch-1",
        question="ETH up or down above 3000 in 1h",
        symbol="ETH",
        yes_token_id="20001",
        no_token_id="20002",
        yes_price=0.55,
        no_price=0.45,
        liquidity=100000.0,
        volume_24h=25000.0,
        end_date=datetime.utcnow() + timedelta(hours=2),
        is_active=True,
        market_type="binary_updown",
        duration_minutes=60,
    )


def make_weather_market():
    return CLIMarket(
        condition_id="weather-orch-1",
        question="Will NYC high temperature be above 75F on May 3?",
        symbol="WEATHER",
        yes_token_id="30001",
        no_token_id="30002",
        yes_price=0.45,
        no_price=0.55,
        liquidity=10000.0,
        volume_24h=1000.0,
        end_date=datetime.utcnow() + timedelta(hours=12),
        is_active=True,
        market_type="bullish",
        price_target=75.0,
    )


def test_arbitrage_decisions_use_explicit_basket_leg_size(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        _data_dir_override=tmp_path / "arb_explicit_size",
        max_position_usd=30.0,
        min_position_usd=5.0,
        min_arb_edge_percent=1.0,
    )
    orchestrator = PolymarketCLIOrchestrator(cfg)
    market = make_market()
    opportunity = ArbitrageOpportunity(
        arb_type="weather_range_no_basket",
        markets=[market],
        description="fixture",
        edge_percent=3.0,
        recommended_trades=[
            {
                "side": "NO",
                "market_id": market.condition_id,
                "token_id": market.no_token_id,
                "price": market.no_price,
                "size_usd": 6.25,
            }
        ],
    )

    decisions = orchestrator._build_arbitrage_decisions([market], [opportunity])

    assert len(decisions) == 1
    assert decisions[0][0].size_usd == 6.25


def test_arbitrage_basket_precheck_blocks_incomplete_position_capacity(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        _data_dir_override=tmp_path / "arb_basket_precheck",
        max_positions=1,
        max_positions_per_symbol=64,
        max_positions_per_direction=64,
    )
    orchestrator = PolymarketCLIOrchestrator(cfg)
    first = make_market()
    second = make_market()
    second.condition_id = "mkt-orch-2"
    decisions = []
    for market in (first, second):
        decisions.append(
            (
                TradeDecision(
                    market_id=market.condition_id,
                    timestamp=datetime.utcnow(),
                    should_trade=True,
                    side="NO",
                    size_usd=5.0,
                    price=market.no_price,
                    confidence=0.75,
                    reason="basket fixture",
                    source="arbitrage",
                    prediction_path="arb_basket|fixture|2",
                ),
                market,
                "arbitrage",
            )
        )

    filtered, blocked = orchestrator._precheck_arbitrage_baskets(decisions, remaining_budget=100.0)

    assert filtered == []
    assert len(blocked) == 2
    assert {item["reason"] for item in blocked} == {"ARBITRAGE_BASKET_PRECHECK"}


def test_live_arbitrage_basket_failure_unwinds_and_blocks_remaining(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.LIVE,
        _data_dir_override=tmp_path / "live_basket_abort",
        max_positions=64,
        max_positions_per_symbol=64,
        max_positions_per_direction=64,
        max_total_exposure_usd=100.0,
        max_position_usd=10.0,
        max_per_market_usd=10.0,
        live_balance_reserve_usd=0.0,
    )
    orchestrator = PolymarketCLIOrchestrator(cfg)
    markets = []
    decisions = []
    for idx, price in enumerate((0.90, 0.80, 0.70), start=1):
        market = make_weather_market()
        market.condition_id = f"weather-basket-{idx}"
        market.no_price = price
        market.yes_price = 1.0 - price
        market.no_token_id = f"no-{idx}"
        markets.append(market)
        decisions.append(
            (
                TradeDecision(
                    market_id=market.condition_id,
                    timestamp=datetime.utcnow(),
                    should_trade=True,
                    side="NO",
                    size_usd=5.0,
                    price=price,
                    confidence=0.75,
                    reason="basket fixture",
                    source="arbitrage",
                    prediction_path="arb_basket|fixture|3",
                ),
                market,
                "arbitrage",
            )
        )

    class BasketAbortTrader:
        def __init__(self):
            self.calls = 0
            self.closed = []
            self.last_reject_reason = None
            self.last_fill_status = None

        def execute_trade(self, decision, market):
            self.calls += 1
            if self.calls == 1:
                return TradeExecution(
                    trade_id="filled-1",
                    market_id=market.condition_id,
                    token_id=market.no_token_id,
                    side=decision.side,
                    size_usd=decision.size_usd,
                    price=decision.price,
                    status="filled",
                    execution_mode="live",
                    timestamp=datetime.utcnow(),
                    order_id="order-1",
                )
            self.last_reject_reason = {"phase": "live", "reason": "not_filled"}
            return None

        def close_position(self, market_id, close_price, reason=""):
            self.closed.append((market_id, close_price, reason))
            return 0.0

    orchestrator.trader = BasketAbortTrader()

    ledger = orchestrator._execute_cycle_plan(decisions, {"cycle": 1})

    assert orchestrator.trader.calls == 2
    assert len(ledger["executed"]) == 1
    assert len(ledger["skipped"]) == 1
    assert len(ledger["blocked"]) == 1
    assert ledger["blocked"][0]["reason"] == "ARBITRAGE_BASKET_ABORTED"
    assert orchestrator.trader.closed == [("weather-basket-1", 0.9, "arbitrage_basket_abort")]
    assert any(item["status"] == "arbitrage_basket_unwind" for item in ledger["fill_outcomes"])
    risk = orchestrator.risk_manager.get_risk_summary()
    assert risk["halted"] is True
    assert risk["halt_reason_code"] == "ARB_BASKET_PARTIAL"


def test_live_weather_plan_requires_release_even_when_manual_flag_enabled(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.LIVE,
        market_vertical="weather",
        allow_live_weather_trading=True,
        _data_dir_override=tmp_path / "weather_release_gate",
        max_positions=64,
        max_positions_per_symbol=64,
        max_positions_per_direction=64,
        max_total_exposure_usd=100.0,
        max_position_usd=10.0,
        max_per_market_usd=10.0,
    )
    orchestrator = PolymarketCLIOrchestrator(cfg)
    market = make_weather_market()
    decision = TradeDecision(
        market_id=market.condition_id,
        timestamp=datetime.utcnow(),
        should_trade=True,
        side="YES",
        size_usd=5.0,
        price=market.yes_price,
        confidence=0.75,
        reason="release gate fixture",
        source="swarm",
    )

    class ExplodingTrader:
        last_reject_reason = None
        last_fill_status = None

        def execute_trade(self, _decision, _market):
            raise AssertionError("orchestrator should block weather live before trader")

    orchestrator.trader = ExplodingTrader()
    cycle_summary = {"cycle": 1}

    ledger = orchestrator._execute_cycle_plan([(decision, market, "swarm")], cycle_summary)

    assert ledger["planned"] == []
    assert ledger["executed"] == []
    assert ledger["blocked"][0]["reason"] == "WEATHER_LIVE_ELIGIBILITY_FAILED"
    assert "weather_release_certificate_missing" in ledger["blocked"][0]["detail"]
    assert cycle_summary["weather_live_eligibility"]["eligible"] is False


def test_run_one_cycle_stubs_produce_schemas(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        cycle_interval_seconds=0,
        max_markets_to_analyze=1,
        _data_dir_override=tmp_path / "polymarket_run",
        max_position_usd=25.0,
        min_position_usd=5.0,
        paper_starting_balance=1000.0,
    )
    orchestrator = PolymarketCLIOrchestrator(cfg)
    market = make_market()

    orchestrator.scanner.scan_markets = lambda force_refresh=False: [market]
    orchestrator.scanner.rank_markets = lambda markets: [(m, 1.0) for m in markets]
    orchestrator.whale_tracker.scan_whales = lambda: []
    orchestrator.signals.get_signals = lambda symbols: {}
    orchestrator.risk_manager.refresh_position_prices = lambda _cli: {}
    orchestrator.risk_manager.check_resolved_markets = lambda _cli: []
    orchestrator.analyzer.analyze_market = (
        lambda *_args, **_kwargs: type(
            "FakeConsensus",
            (),
            {
                "consensus_prediction": "YES",
                "consensus_probability": 0.6,
                "consensus_confidence": 0.75,
            },
        )()
    )
    orchestrator._build_arbitrage_decisions = lambda _markets, _opportunities: []
    orchestrator._build_swarm_decision = (
        lambda market, price_context, portfolio_positions: TradeDecision(
            market_id=market.condition_id,
            timestamp=datetime.utcnow(),
            should_trade=True,
            side="YES",
            size_usd=10.0,
            price=market.yes_price,
            confidence=0.8,
            reason="test",
            source="swarm",
        )
    )
    orchestrator._should_scan_whales = lambda: False

    fake_cli = StubCLI()
    orchestrator.trader = CLITrader(config=cfg, cli=fake_cli, risk_manager=orchestrator.risk_manager)
    orchestrator.trader.cli = fake_cli

    summaries = orchestrator.run(cycles=1)
    assert summaries and isinstance(summaries, list)
    summary = summaries[0]
    assert summary["status"] == "complete"
    assert summary["trades_executed"] == 1
    assert summary["cycle"] == 1

    run_audit_path = cfg.data_dir / "run_audit.jsonl"
    assert run_audit_path.exists()
    run_audit = json.loads(run_audit_path.read_text().splitlines()[-1])
    assert run_audit["cycle"] == 1
    assert run_audit["execution_mode"] == ExecutionMode.DRY_RUN.value
    assert run_audit["trades_executed"] == 1
    assert "swarm_runtime" in run_audit
    assert any(item["phase"] == "market_scan" for item in run_audit["phase_progress"])

    cycle_summaries = list(cfg.cycles_dir.glob("cycle_*.json"))
    assert cycle_summaries
    parsed_cycle = json.loads(cycle_summaries[0].read_text())
    assert parsed_cycle["execution_mode"] == ExecutionMode.DRY_RUN.value
    assert parsed_cycle["cycle"] == 1
    assert parsed_cycle["current_phase_status"] == "complete"

    current_cycle_path = cfg.data_dir / "current_cycle.json"
    assert current_cycle_path.exists()
    current_cycle = json.loads(current_cycle_path.read_text())
    assert any(item["phase"] == "execute_plan" for item in current_cycle["phase_progress"])
    assert current_cycle["current_phase"] == "cycle"
    assert "swarm_runtime" in current_cycle

    trade_file = cfg.trades_dir / f"trades_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"
    assert trade_file.exists()
    trade_record = json.loads(trade_file.read_text().splitlines()[0])
    assert trade_record["execution_mode"] == "dry_run"
    assert trade_record["status"] == "simulated"


class PaperModeStubCLI:
    def __init__(self, price_book=None):
        self.price_book = price_book or {"asks": [{"size": "200", "price": "0.55"}]}

    def get_order_book(self, _token_id):
        return self.price_book

    def get_clob_market(self, _market_id):
        return {"closed": False, "active": True, "tokens": []}


def test_run_one_cycle_paper_stubs_produce_schemas(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.PAPER,
        cycle_interval_seconds=0,
        max_markets_to_analyze=1,
        _data_dir_override=tmp_path / "polymarket_run_paper",
        max_position_usd=25.0,
        min_position_usd=5.0,
        paper_starting_balance=1000.0,
        order_fill_timeout_seconds=10,
    )
    orchestrator = PolymarketCLIOrchestrator(cfg)
    market = make_market()

    orchestrator.scanner.scan_markets = lambda force_refresh=False: [market]
    orchestrator.scanner.rank_markets = lambda markets: [(m, 1.0) for m in markets]
    orchestrator.whale_tracker.scan_whales = lambda: []
    orchestrator.signals.get_signals = lambda symbols: {}
    orchestrator.risk_manager.refresh_position_prices = lambda _cli: {}
    orchestrator.risk_manager.check_resolved_markets = lambda _cli: []
    orchestrator._build_swarm_decision = (
        lambda market, price_context, portfolio_positions: TradeDecision(
            market_id=market.condition_id,
            timestamp=datetime.utcnow(),
            should_trade=True,
            side="YES",
            size_usd=10.0,
            price=market.yes_price,
            confidence=0.8,
            reason="test",
            source="swarm",
        )
    )
    orchestrator.arbitrage_detector.detect_all = lambda _markets: []
    orchestrator._should_scan_whales = lambda: False

    fake_cli = PaperModeStubCLI()
    orchestrator.trader = CLITrader(config=cfg, cli=fake_cli, risk_manager=orchestrator.risk_manager)
    orchestrator.trader.cli = fake_cli

    summaries = orchestrator.run(cycles=1)
    assert summaries and isinstance(summaries, list)
    summary = summaries[0]
    assert summary["status"] == "complete"
    assert summary["trades_executed"] == 1
    assert summary["cycle"] == 1

    run_audit_path = cfg.data_dir / "run_audit.jsonl"
    assert run_audit_path.exists()
    run_audit = json.loads(run_audit_path.read_text().splitlines()[-1])
    assert run_audit["cycle"] == 1
    assert run_audit["execution_mode"] == ExecutionMode.PAPER.value
    assert run_audit["trades_executed"] == 1
    assert "swarm_runtime" in run_audit

    cycle_summaries = list(cfg.cycles_dir.glob("cycle_*.json"))
    assert cycle_summaries
    parsed_cycle = json.loads(cycle_summaries[0].read_text())
    assert parsed_cycle["execution_mode"] == ExecutionMode.PAPER.value
    assert parsed_cycle["cycle"] == 1

    trade_file = cfg.trades_dir / f"trades_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"
    assert trade_file.exists()
    trade_record = json.loads(trade_file.read_text().splitlines()[0])
    assert trade_record["execution_mode"] == "paper"
    assert trade_record["status"] == "paper_filled"
    assert trade_record["size_usd"] >= cfg.min_position_usd
    assert trade_record["fees"] > 0


def test_get_run_status_returns_dashboard_fields(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        cycle_interval_seconds=60,
        max_markets_to_analyze=1,
        _data_dir_override=tmp_path / "pm_status",
    )
    orchestrator = PolymarketCLIOrchestrator(cfg)
    orchestrator.cli = StubStatusCLI()

    status = orchestrator.get_run_status()

    assert status["execution_mode"] == ExecutionMode.DRY_RUN.value
    assert status["cycle"] == 0
    assert status["cycles_completed"] == 0
    assert status["trades_executed"] == 0
    assert status["rejections"] == 0
    assert status["paper_balance"] >= 0
    assert status["cli_status"]["cli_status_ok"] is True
    assert status["risk_status"]["positions"] == 0
    assert status["risk_status"]["halted"] is False


def test_weather_cycle_routes_market_specific_context(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        search_symbols=["WEATHER"],
        cycle_interval_seconds=0,
        max_markets_to_analyze=1,
        _data_dir_override=tmp_path / "pm_weather",
        min_position_usd=5.0,
        max_position_usd=25.0,
    )
    orchestrator = PolymarketCLIOrchestrator(cfg)
    market = make_weather_market()
    captured = {}

    orchestrator.scanner.scan_markets = lambda force_refresh=False: [market]
    orchestrator.scanner.rank_markets = lambda markets: [(m, 1.0) for m in markets]
    orchestrator.whale_tracker.scan_whales = lambda: []
    orchestrator.risk_manager.refresh_position_prices = lambda _cli: {}
    orchestrator.risk_manager.check_resolved_markets = lambda _cli: []
    orchestrator.arbitrage_detector.detect_all = lambda _markets: []
    orchestrator._should_scan_whales = lambda: False

    class WeatherSignalStub:
        def get_market_context(self, markets):
            return {
                markets[0].condition_id: {
                    "status": "ok",
                    "weather_probability": 0.72,
                    "weather_signal": "NYC forecast clears threshold",
                }
            }

        def get_signals(self, symbols):
            raise AssertionError("weather mode should not call crypto symbol signals")

    orchestrator.signals = WeatherSignalStub()

    def fake_build_swarm_decision(market, price_context, portfolio_positions):
        captured["price_context"] = price_context
        return None

    orchestrator._build_swarm_decision = fake_build_swarm_decision

    summaries = orchestrator.run(cycles=1)

    assert summaries[0]["status"] == "complete"
    assert captured["price_context"]["weather-orch-1"]["weather_probability"] == 0.72
    assert any(item["phase"] == "weather_signals" for item in summaries[0]["phase_progress"])


def test_weather_arbitrage_scans_full_market_universe(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        search_symbols=["WEATHER"],
        cycle_interval_seconds=0,
        max_markets_to_analyze=1,
        _data_dir_override=tmp_path / "pm_weather_full_arb_scan",
    )
    orchestrator = PolymarketCLIOrchestrator(cfg)
    markets = []
    for idx in range(3):
        market = make_weather_market()
        market.condition_id = f"weather-orch-{idx + 1}"
        market.question = f"Will NYC high temperature be between {70 + idx}-{71 + idx}F on May 3?"
        markets.append(market)

    captured = {}
    orchestrator.scanner.scan_markets = lambda force_refresh=False: markets
    orchestrator.scanner.rank_markets = lambda raw_markets: [(raw_markets[0], 1.0)]
    orchestrator.signals.get_market_context = lambda selected: {}
    orchestrator.whale_tracker.scan_whales = lambda: []
    orchestrator.risk_manager.refresh_position_prices = lambda _cli: {}
    orchestrator.risk_manager.check_resolved_markets = lambda _cli: []
    orchestrator._build_swarm_decision = lambda **_kwargs: None
    orchestrator._should_scan_whales = lambda: False

    def capture_detect_all(scanned_markets):
        captured["ids"] = [market.condition_id for market in scanned_markets]
        return []

    orchestrator.arbitrage_detector.detect_all = capture_detect_all

    summaries = orchestrator.run(cycles=1)

    assert summaries[0]["status"] == "complete"
    assert captured["ids"] == [market.condition_id for market in markets]


def test_weather_cycle_can_auto_ingest_high_resolution_before_signals(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        search_symbols=["WEATHER"],
        cycle_interval_seconds=0,
        max_markets_to_analyze=1,
        weather_auto_ingest_high_resolution=True,
        weather_high_resolution_cache_dir=str(tmp_path / "cache"),
        _data_dir_override=tmp_path / "pm_weather_high_res",
    )
    orchestrator = PolymarketCLIOrchestrator(cfg)
    market = make_weather_market()
    calls = []

    orchestrator.scanner.scan_markets = lambda force_refresh=False: [market]
    orchestrator.scanner.rank_markets = lambda markets: [(m, 1.0) for m in markets]
    orchestrator.whale_tracker.scan_whales = lambda: []
    orchestrator.risk_manager.refresh_position_prices = lambda _cli: {}
    orchestrator.risk_manager.check_resolved_markets = lambda _cli: []
    orchestrator.arbitrage_detector.detect_all = lambda _markets: []
    orchestrator._build_swarm_decision = lambda **_kwargs: None
    orchestrator._should_scan_whales = lambda: False

    class WeatherSignalStub:
        def get_market_context(self, markets):
            calls.append(("signals", [market.condition_id for market in markets]))
            return {}

    class HighResCycleStub:
        def run(self, markets, dry_run=False, force=False):
            calls.append(("high_res", [market.condition_id for market in markets], dry_run, force))
            return WeatherHighResolutionCycleReport(
                status="live_safe_cache_ready",
                generated_at=datetime.utcnow().isoformat(),
                cache_dir=str(tmp_path / "cache"),
                total_markets=len(markets),
                total_items=1,
                planned_count=0,
                ingested_count=1,
                cache_hit_count=0,
                skipped_count=0,
                blocked_count=0,
                dry_run=dry_run,
            )

    orchestrator.signals = WeatherSignalStub()
    orchestrator._weather_high_res_cycle_runner = HighResCycleStub()

    summaries = orchestrator.run(cycles=1)

    assert summaries[0]["status"] == "complete"
    assert calls[0][0] == "high_res"
    assert calls[1][0] == "signals"
    assert summaries[0]["weather_high_resolution_ingest"]["ingested_count"] == 1
    assert any(item["phase"] == "weather_high_resolution_ingest" for item in summaries[0]["phase_progress"])


def test_weather_pretrade_gate_requires_accepted_alpha_report(tmp_path):
    report_path = tmp_path / "weather_alpha_report.json"
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        search_symbols=["WEATHER"],
        weather_require_alpha_verification=True,
        weather_alpha_report_path=str(report_path),
        _data_dir_override=tmp_path / "pm_weather_gate",
    )
    orchestrator = PolymarketCLIOrchestrator(cfg)
    market = make_weather_market()
    context = {
        market.condition_id: {
            "status": "ok",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "weather_edge_percent": 20.0,
            "weather_probability": 0.70,
            "weather_confidence": 0.70,
            "recommended_side": "YES",
            "selected_source_family": "open_meteo",
            "source_statuses": {
                "station_mapper": "ok",
                "open_meteo_forecast": "live_safe",
            },
        }
    }

    ok, reason = orchestrator._weather_pretrade_gate(market, context)
    assert ok is False
    assert reason.startswith("weather_alpha_report_missing")

    report_path.write_text(
        json.dumps(
            {
                "deployment_verdict": {
                    "accepted_for_live_weather_trading": False,
                    "blockers": ["model_brier_not_better_than_market"],
                }
            }
        ),
        encoding="utf-8",
    )
    ok, reason = orchestrator._weather_pretrade_gate(market, context)
    assert ok is False
    assert reason.startswith("weather_alpha_not_accepted")

    report_path.write_text(
        json.dumps(
            {
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "validated_source_families": ["open_meteo"],
                "validated_min_probability_gap": 0.08,
                "deployment_verdict": {
                    "accepted_for_live_weather_trading": True,
                    "feature_schema_version": FEATURE_SCHEMA_VERSION,
                    "validated_source_families": ["open_meteo"],
                    "validated_min_probability_gap": 0.08,
                },
            }
        ),
        encoding="utf-8",
    )
    ok, reason = orchestrator._weather_pretrade_gate(market, context)
    assert ok is True
    assert reason == "ok"
