from datetime import date, datetime, timedelta
import pytest

from src.agents.polymarket_trader.config import get_polymarket_cli_config
from src.agents.polymarket_trader.models import TradeExecution
from src.agents.polymarket_trader.risk_manager import STATE_RESOLVED_STALE_SECONDS, RiskManager


class MarketResolutionCLIStub:
    def __init__(self, payload):
        self.payload = payload

    def get_clob_market(self, _market_id):
        return self.payload


class LiveOrderCLIStub:
    def __init__(self, open_orders=None, trades=None):
        self._open_orders = open_orders if open_orders is not None else []
        self._trades = trades if trades is not None else []

    def get_open_orders(self):
        return self._open_orders

    def get_trades(self):
        return self._trades


def test_check_resolved_markets_stale_closed_no_winner_recovers_to_entry_price(tmp_path):
    cfg = get_polymarket_cli_config(_data_dir_override=tmp_path / "risk_state")
    rm = RiskManager(cfg)
    rm.positions.clear()
    rm._unresolved_closed_markets.clear()

    execution = TradeExecution(
        trade_id="t-1",
        market_id="m-nowinner",
        token_id="10001",
        side="YES",
        size_usd=10.0,
        price=0.60,
        status="simulated",
        execution_mode="dry_run",
        timestamp=datetime.utcnow(),
    )
    rm.add_position(
        execution,
        question="ETH up or down test",
        symbol="ETH",
        source="test",
    )

    market_payload = {
        "closed": True,
        "active": False,
        "tokens": [
            {"winner": False, "outcome": "NO"},
            {"winner": False, "outcome": "YES"},
        ],
    }
    resolved = rm.check_resolved_markets(MarketResolutionCLIStub(market_payload))
    assert resolved == []
    assert "m-nowinner" in rm._unresolved_closed_markets

    rm._unresolved_closed_markets["m-nowinner"] = (
        datetime.utcnow().timestamp() - (STATE_RESOLVED_STALE_SECONDS + 5)
    )
    resolved = rm.check_resolved_markets(MarketResolutionCLIStub(market_payload))
    assert len(resolved) == 1
    assert resolved[0]["market_id"] == "m-nowinner"
    assert resolved[0]["resolution_source"] == "stale_recovery"
    assert resolved[0]["outcome"] == ""
    assert resolved[0]["our_side_won"] is False
    assert "m-nowinner" not in rm.positions


def test_check_resolved_markets_close_by_winner_flag(tmp_path):
    cfg = get_polymarket_cli_config(_data_dir_override=tmp_path / "risk_state_winner")
    rm = RiskManager(cfg)
    rm.positions.clear()

    execution = TradeExecution(
        trade_id="t-2",
        market_id="m-winner",
        token_id="10002",
        side="NO",
        size_usd=8.0,
        price=0.20,
        status="simulated",
        execution_mode="dry_run",
        timestamp=datetime.utcnow() - timedelta(minutes=1),
    )
    rm.add_position(
        execution,
        question="BTC up or down test",
        symbol="BTC",
        source="test",
    )

    market_payload = {
        "closed": True,
        "active": False,
        "tokens": [
            {"winner": False, "outcome": "YES"},
            {"winner": True, "outcome": "NO"},
        ],
    }
    resolved = rm.check_resolved_markets(MarketResolutionCLIStub(market_payload))
    assert len(resolved) == 1
    assert resolved[0]["market_id"] == "m-winner"
    assert resolved[0]["outcome"] == "NO"
    assert resolved[0]["our_side_won"]
    assert resolved[0]["pnl"] == pytest.approx(32.0)


def test_invalid_position_contract_enforced(tmp_path):
    cfg = get_polymarket_cli_config(_data_dir_override=tmp_path / "risk_state_invalid")
    rm = RiskManager(cfg)
    rm.positions.clear()

    invalid_execution = TradeExecution(
        trade_id="t-3",
        market_id="m-invalid",
        token_id="99999",
        side="MAYBE",
        size_usd=10.0,
        price=0.50,
        status="simulated",
        execution_mode="dry_run",
        timestamp=datetime.utcnow(),
    )
    rm._unresolved_closed_markets.clear()

    with pytest.raises(ValueError):
        rm.add_position(
            invalid_execution,
            question="Invalid side",
            symbol="ETH",
            source="test",
        )

    good_execution = TradeExecution(
        trade_id="t-4",
        market_id="m-valid",
        token_id="10003",
        side="YES",
        size_usd=10.0,
        price=0.50,
        status="simulated",
        execution_mode="dry_run",
        timestamp=datetime.utcnow(),
    )
    rm.add_position(good_execution, question="Good 1", symbol="ETH", source="test")
    with pytest.raises(ValueError):
        rm.add_position(good_execution, question="Duplicate", symbol="ETH", source="test")


def test_can_trade_rejects_invalid_inputs(tmp_path):
    cfg = get_polymarket_cli_config(_data_dir_override=tmp_path / "risk_state_inputs")
    rm = RiskManager(cfg)
    rm.positions.clear()
    rm.daily_pnl = 0.0
    rm._halted = False
    rm._halt_reason = ""

    allowed, reason = rm.can_trade(
        market_id="m-invalid-side",
        size_usd=10.0,
        symbol="ETH",
        side="BAD",
        end_date=None,
    )
    assert allowed is False
    assert "INVALID_SIDE" in reason

    allowed, reason = rm.can_trade(
        market_id="m-expired",
        size_usd=10.0,
        symbol="ETH",
        side="YES",
        end_date=datetime.utcnow() - timedelta(minutes=1),
    )
    assert allowed is False
    assert "EXPIRED_MARKET" in reason


def test_daily_halt_resume_with_legacy_code(tmp_path):
    cfg = get_polymarket_cli_config(_data_dir_override=tmp_path / "risk_state_daily")
    rm = RiskManager(cfg)
    rm.halt_trading("daily loss", "DAILY_LOSS")

    assert rm._halted is True
    assert rm._halt_reason_code == "DAILY_LOSS"

    rm._today = (date.today() - timedelta(days=1)).isoformat()
    rm._check_daily_reset()
    assert rm._halted is False
    assert rm._halt_reason_code == "DAILY_RESET"


def test_live_order_registry_persists_and_reconciles_on_restart(tmp_path):
    cfg = get_polymarket_cli_config(_data_dir_override=tmp_path / "risk_live_orders")
    rm = RiskManager(cfg)
    rm.register_live_order(
        order_id="order-restart",
        market_id="m-restart",
        token_id="20001",
        side="YES",
        requested_size_usd=4.0,
        submitted_shares=5.0,
        submitted_notional_usd=4.0,
        decision_price=0.80,
        placed_price=0.80,
        execution_mode="live",
    )
    assert rm.live_orders["order-restart"]["status"] == "submitted"

    rm_reloaded = RiskManager(cfg)
    assert "order-restart" in rm_reloaded.live_orders

    updates = rm_reloaded.reconcile_live_orders(
        LiveOrderCLIStub(
            trades=[
                {
                    "order_id": "order-restart",
                    "market_id": "m-restart",
                    "token_id": "20001",
                    "price": 0.81,
                    "size": 5.0,
                }
            ]
        )
    )
    assert updates
    assert rm_reloaded.live_orders["order-restart"]["final_disposition"] == "filled"
    assert rm_reloaded.live_orders["order-restart"]["reconciliation_status"] == "trade_match"


def test_live_order_registry_tracks_timeout_and_orphan_states(tmp_path):
    cfg = get_polymarket_cli_config(_data_dir_override=tmp_path / "risk_live_timeout")
    rm = RiskManager(cfg)
    rm.register_live_order(
        order_id="order-timeout",
        market_id="m-timeout",
        token_id="20002",
        side="YES",
        requested_size_usd=4.0,
        submitted_shares=5.0,
        submitted_notional_usd=4.0,
        decision_price=0.80,
        placed_price=0.80,
        execution_mode="live",
    )
    rm.apply_live_order_result(
        "order-timeout",
        {"status": "timeout_cancel_failed", "reason": "cancel failed"},
    )

    record = rm.live_orders["order-timeout"]
    assert record["status"] == "timeout_cancel_failed"
    assert record["reconciliation_status"] == "orphaned_pending_reconciliation"

    allowed, reason = rm.can_trade(market_id="new-market", size_usd=5.0, symbol="ETH", side="YES")
    assert allowed is False
    assert "ORPHANED_LIVE_ORDER" in reason


def test_live_order_registry_marks_cancelled_terminal_state(tmp_path):
    cfg = get_polymarket_cli_config(_data_dir_override=tmp_path / "risk_live_cancelled")
    rm = RiskManager(cfg)
    rm.register_live_order(
        order_id="order-cancelled",
        market_id="m-cancelled",
        token_id="20003",
        side="YES",
        requested_size_usd=4.0,
        submitted_shares=5.0,
        submitted_notional_usd=4.0,
        decision_price=0.80,
        placed_price=0.80,
        execution_mode="live",
    )
    rm.apply_live_order_result("order-cancelled", {"status": "timeout_cancelled"})

    record = rm.live_orders["order-cancelled"]
    assert record["status"] == "timeout_cancelled"
    assert record["final_disposition"] == "cancelled"


def test_circuit_breakers_cover_unrealized_loss_and_stale_live_orders(tmp_path):
    cfg = get_polymarket_cli_config(
        _data_dir_override=tmp_path / "risk_circuit_breakers",
        unrealized_loss_limit_usd=5.0,
        live_order_stale_seconds=60,
    )
    rm = RiskManager(cfg)
    rm.positions.clear()
    rm.live_orders.clear()
    rm.daily_pnl = 0.0
    rm._halted = False
    rm._halt_reason = ""
    rm._halt_reason_code = ""

    execution = TradeExecution(
        trade_id="t-loss",
        market_id="m-loss",
        token_id="30001",
        side="YES",
        size_usd=10.0,
        price=0.50,
        status="simulated",
        execution_mode="dry_run",
        timestamp=datetime.utcnow(),
    )
    pos = rm.add_position(execution, question="ETH test", symbol="ETH", source="test")
    pos.update_price(0.10)
    rm.check_circuit_breakers()
    assert rm._halt_reason_code == "UNREALIZED_LOSS_LIMIT"

    rm.resume_trading()
    rm.positions.clear()
    rm.live_orders.clear()
    rm.register_live_order(
        order_id="order-stale",
        market_id="m-stale",
        token_id="20004",
        side="YES",
        requested_size_usd=4.0,
        submitted_shares=5.0,
        submitted_notional_usd=4.0,
        decision_price=0.80,
        placed_price=0.80,
        execution_mode="live",
    )
    rm.live_orders["order-stale"]["created_at"] = datetime.utcnow().timestamp() - 120
    rm.check_circuit_breakers()
    assert rm._halt_reason_code == "STALE_LIVE_ORDER"
