from src.agents.polymarket_trader.config import get_polymarket_cli_config
from src.agents.polymarket_trader.preflight import run_preflight_checks


class StubCLI:
    def __init__(
        self,
        health,
        wallet_address="0xdeadbeef000000000000000000000000000000beef",
        balance=200.0,
        open_orders=None,
        cancel_result=None,
        fail_cancel=False,
    ):
        self._health = health
        self._wallet_address = wallet_address
        self._balance = balance
        self._open_orders = open_orders if open_orders is not None else []
        self._cancel_result = cancel_result if cancel_result is not None else {"ok": True}
        self._fail_cancel = fail_cancel

    def get_health_status(self):
        return self._health

    def get_wallet_address(self):
        return self._wallet_address

    def get_balance(self):
        return {"balance": self._balance}

    def get_open_orders(self):
        return self._open_orders

    def cancel_all_orders(self):
        if self._fail_cancel:
            raise RuntimeError("cancel failed")
        return self._cancel_result


def _base_health(
    cli_status_ok=True,
    permissions_ok=True,
    wallet_configured=True,
    balance_read_ok=True,
    balance=200.0,
    cli_binary="polymarket",
):
    return {
        "cli_binary": cli_binary,
        "cli_available": bool(cli_status_ok),
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
        "cli_status_ok": cli_status_ok,
        "wallet_configured": wallet_configured,
        "wallet_address": "0xwallet",
        "balance_read_ok": balance_read_ok,
        "balance": balance,
        "permissions_ok": permissions_ok,
        "permission_failures": [],
        "timestamp": 0,
    }


def test_preflight_allows_permissions_warning_without_failing_hard():
    cfg = get_polymarket_cli_config(
        use_direct_api=False,
        live_min_balance_usd=50.0,
        max_total_exposure_usd=20.0,
        max_position_usd=10.0,
        live_max_position_usd=10.0,
        live_balance_reserve_usd=0.0,
        _data_dir_override=None,
    )
    cli = StubCLI(
        health=_base_health(cli_status_ok=True, permissions_ok=False, balance=200.0),
        balance=200.0,
    )

    assert run_preflight_checks(cfg, cli) is True


def test_preflight_fails_when_cli_transport_unavailable():
    cfg = get_polymarket_cli_config(
        use_direct_api=False,
        live_min_balance_usd=10.0,
        max_total_exposure_usd=5.0,
        max_position_usd=5.0,
        live_max_position_usd=5.0,
        live_balance_reserve_usd=0.0,
    )
    cli = StubCLI(
        health=_base_health(cli_status_ok=False, wallet_configured=False, balance_read_ok=False, balance=0.0),
        wallet_address=None,
        balance=0.0,
    )

    assert run_preflight_checks(cfg, cli) is False


def test_preflight_fails_on_balance_shortfall():
    cfg = get_polymarket_cli_config(
        use_direct_api=False,
        live_min_balance_usd=100.0,
        max_total_exposure_usd=20.0,
        max_position_usd=10.0,
        live_max_position_usd=10.0,
        live_balance_reserve_usd=0.0,
    )
    cli = StubCLI(
        health=_base_health(cli_status_ok=True, permissions_ok=True, balance=10.0),
        balance=10.0,
    )

    assert run_preflight_checks(cfg, cli) is False


def test_preflight_fails_when_wallet_missing():
    cfg = get_polymarket_cli_config(
        use_direct_api=False,
        max_total_exposure_usd=20.0,
        max_position_usd=10.0,
        live_max_position_usd=10.0,
        live_balance_reserve_usd=0.0,
    )
    cli = StubCLI(
        health=_base_health(cli_status_ok=True, wallet_configured=True),
        wallet_address=None,
        balance=1000.0,
    )

    assert run_preflight_checks(cfg, cli) is False
