from src.agents.polymarket_trader.config import get_polymarket_cli_config
from src.agents.polymarket_trader.trader import CLITrader
from src.agents.polymarket_trader import trader as trader_module
from src.agents.polymarket_trader.risk_manager import RiskManager
from src.agents.polymarket_trader.models import CLIMarket, TradeDecision
from datetime import datetime


class FillExternalStubCLI:
    def __init__(self):
        self.calls = 0

    def get_open_orders(self, _market_id=None):
        return []

    def get_trades(self, _market_id=None):
        self.calls += 1
        if self.calls == 1:
            return []
        return [
            {
                "order_id": "different-order",
                "token_id": "token-external",
                "price": "0.41",
                "amount": "12",
                "fee": "0.01",
            }
        ]


def make_monotonic_clock(monkeypatch):
    state = {"t": 0.0}

    def monotonic():
        return state["t"]

    def sleep(seconds):
        state["t"] += seconds

    monkeypatch.setattr(trader_module.time, "monotonic", monotonic)
    monkeypatch.setattr(trader_module.time, "sleep", sleep)


def test_wait_for_fill_detects_external_token_fill(monkeypatch):
    cfg = get_polymarket_cli_config(order_fill_timeout_seconds=10)
    cli = FillExternalStubCLI()
    trader = CLITrader(config=cfg, cli=cli, risk_manager=RiskManager(cfg))
    make_monotonic_clock(monkeypatch)

    result = trader._wait_for_fill_deterministic(
        order_id="order-1",
        token_id="token-external",
        market_id="m-ext",
        timeout=5,
    )

    assert result is not None
    assert result["status"] == "filled_external"
    assert result["source"] == "external_token_match"


class TimeoutFillStubCLI:
    def get_open_orders(self, _market_id=None):
        return [{"id": "order-timeout"}]

    def get_trades(self, _market_id=None):
        return []

    def cancel_order(self, _order_id):
        return None


class EmptyOrderBookCLI:
    def get_order_book(self, _token_id):
        return {"asks": []}


class ShareFloorRejectCLI(EmptyOrderBookCLI):
    def __init__(self):
        self.order_submit_called = False

    def get_midpoint(self, _token_id):
        return {"mid": 0.80}

    def get_balance(self):
        return {"balance": 100.0}

    def create_limit_order(self, **_kwargs):
        self.order_submit_called = True
        return {"orderID": "should-not-submit"}


class LiveOrderTypeStubCLI(EmptyOrderBookCLI):
    def __init__(self):
        self.order_type = None

    def get_midpoint(self, _token_id):
        return {"mid": 0.50}

    def get_balance(self):
        return {"balance": 100.0}

    def create_limit_order(self, **kwargs):
        self.order_type = kwargs.get("order_type")
        return {"orderID": "order-basket"}

    def get_open_orders(self, _market_id=None):
        return []

    def get_trades(self, _market_id=None):
        return [
            {
                "orderID": "order-basket",
                "token_id": "1002",
                "price": "0.50",
                "size": "10",
                "fee": "0",
            }
        ]


class RaiseOnLiveTouchCLI:
    def get_order_book(self, _token_id):
        raise AssertionError("weather live gate should block before order book reads")

    def get_midpoint(self, _token_id):
        raise AssertionError("weather live gate should block before midpoint reads")

    def get_balance(self):
        raise AssertionError("weather live gate should block before balance reads")

    def create_limit_order(self, **_kwargs):
        raise AssertionError("weather live gate should block before order submission")


def test_execute_trade_rejects_invalid_decision_price():
    cfg = get_polymarket_cli_config(execution_mode="dry_run")
    market = CLIMarket(
        condition_id="m-invalid-price",
        question="ETH up or down",
        symbol="ETH",
        yes_token_id="1001",
        no_token_id="1002",
        yes_price=0.5,
        no_price=0.5,
        liquidity=1000.0,
        volume_24h=1000.0,
        end_date=None,
        is_active=True,
        market_type="neutral",
        duration_minutes=None,
    )
    trader = CLITrader(config=cfg, cli=EmptyOrderBookCLI(), risk_manager=RiskManager(cfg))
    execution = trader.execute_trade(
        TradeDecision(
            market_id=market.condition_id,
            timestamp=datetime.utcnow(),
            should_trade=True,
            side="YES",
            size_usd=5.0,
            price=0.0,
            confidence=0.8,
            reason="bad",
            source="swarm",
        ),
        market,
    )

    assert execution is None
    assert trader.last_reject_reason["phase"] == "decision"
    assert trader.last_reject_reason["reason"] == "invalid decision price"


def test_wait_for_fill_timeout_cancel_failed_when_cancel_returns_no_result(monkeypatch):
    cfg = get_polymarket_cli_config(order_fill_timeout_seconds=1)
    cli = TimeoutFillStubCLI()
    trader = CLITrader(config=cfg, cli=cli, risk_manager=RiskManager(cfg))
    make_monotonic_clock(monkeypatch)

    result = trader._wait_for_fill_deterministic(
        order_id="order-timeout",
        token_id="token-timeout",
        market_id="m-timeout",
        timeout=1,
    )

    assert result is not None
    assert result["status"] == "timeout_cancel_failed"


def test_live_trade_rejects_when_five_share_floor_exceeds_budget(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode="live",
        min_position_usd=0.0,
        max_position_usd=3.0,
        live_max_position_usd=3.0,
        max_total_exposure_usd=10.0,
        live_balance_reserve_usd=0.0,
        _data_dir_override=tmp_path / "live_floor",
    )
    cli = ShareFloorRejectCLI()
    trader = CLITrader(config=cfg, cli=cli, risk_manager=RiskManager(cfg))
    market = CLIMarket(
        condition_id="m-live-floor",
        question="ETH up or down",
        symbol="ETH",
        yes_token_id="1001",
        no_token_id="1002",
        yes_price=0.8,
        no_price=0.2,
        liquidity=1000.0,
        volume_24h=1000.0,
        end_date=None,
        is_active=True,
        market_type="neutral",
        duration_minutes=None,
    )
    execution = trader.execute_trade(
        TradeDecision(
            market_id=market.condition_id,
            timestamp=datetime.utcnow(),
            should_trade=True,
            side="YES",
            size_usd=3.0,
            price=0.80,
            confidence=0.8,
            reason="floor test",
            source="swarm",
        ),
        market,
    )

    assert execution is None
    assert trader.last_reject_reason["phase"] == "live"
    assert trader.last_reject_reason["reason"] == "min_share_floor_exceeds_budget"
    assert cli.order_submit_called is False


def test_live_arbitrage_basket_uses_fill_or_kill_orders(tmp_path, monkeypatch):
    cfg = get_polymarket_cli_config(
        execution_mode="live",
        min_position_usd=0.0,
        max_position_usd=20.0,
        live_max_position_usd=20.0,
        max_total_exposure_usd=50.0,
        live_balance_reserve_usd=0.0,
        order_fill_timeout_seconds=3,
        _data_dir_override=tmp_path / "live_basket_order_type",
    )
    cli = LiveOrderTypeStubCLI()
    trader = CLITrader(config=cfg, cli=cli, risk_manager=RiskManager(cfg))
    make_monotonic_clock(monkeypatch)
    market = CLIMarket(
        condition_id="m-live-basket",
        question="Will ETH be above 4000 on May 5?",
        symbol="ETH",
        yes_token_id="1001",
        no_token_id="1002",
        yes_price=0.5,
        no_price=0.5,
        liquidity=1000.0,
        volume_24h=1000.0,
        end_date=None,
        is_active=True,
        market_type="neutral",
        duration_minutes=None,
    )

    execution = trader.execute_trade(
        TradeDecision(
            market_id=market.condition_id,
            timestamp=datetime.utcnow(),
            should_trade=True,
            side="NO",
            size_usd=5.0,
            price=0.50,
            confidence=0.8,
            reason="basket test",
            source="arbitrage",
            prediction_path="arb_basket|crypto_fixture:eth:2026-05-05|7",
        ),
        market,
    )

    assert execution is not None
    assert execution.status == "filled"
    assert cli.order_type == "FOK"


def test_live_weather_trade_blocks_before_any_live_cli_touch(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode="live",
        market_vertical="weather",
        allow_live_weather_trading=True,
        min_position_usd=0.0,
        max_position_usd=20.0,
        live_max_position_usd=20.0,
        max_total_exposure_usd=50.0,
        _data_dir_override=tmp_path / "live_weather_release_gate",
    )
    trader = CLITrader(config=cfg, cli=RaiseOnLiveTouchCLI(), risk_manager=RiskManager(cfg))
    market = CLIMarket(
        condition_id="weather-release-gate",
        question="Will the highest temperature in Lagos be 33C on May 5?",
        symbol="WEATHER",
        yes_token_id="1001",
        no_token_id="1002",
        yes_price=0.5,
        no_price=0.5,
        liquidity=1000.0,
        volume_24h=1000.0,
        end_date=None,
        is_active=True,
        market_type="neutral",
        duration_minutes=None,
    )

    execution = trader.execute_trade(
        TradeDecision(
            market_id=market.condition_id,
            timestamp=datetime.utcnow(),
            should_trade=True,
            side="YES",
            size_usd=5.0,
            price=0.50,
            confidence=0.8,
            reason="release gate test",
            source="swarm",
        ),
        market,
    )

    assert execution is None
    assert trader.last_reject_reason["phase"] == "live"
    assert trader.last_reject_reason["reason"] == "weather_live_eligibility_failed"
    assert "weather_release_certificate_missing" in trader.last_reject_reason["blockers"]
