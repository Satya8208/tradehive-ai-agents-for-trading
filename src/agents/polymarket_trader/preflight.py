"""
Pre-flight checks for Polymarket CLI live trading.

Validates CLI connectivity, wallet auth, balance, and stale orders
before allowing the orchestrator to start in LIVE mode.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from termcolor import cprint

from .config import PolymarketCLIConfig
from .cli_wrapper import PolymarketCLI


def _parse_balance(balance_data: Any) -> Tuple[float, str]:
    """
    Parse balance payloads from CLI/direct API responses into float and a source hint.
    """
    if balance_data is None:
        return 0.0, "missing_balance_payload"

    if isinstance(balance_data, (int, float)):
        return float(balance_data), "direct_number"

    if not isinstance(balance_data, dict):
        return 0.0, f"unexpected_type:{type(balance_data).__name__}"

    for key in ("balance", "amount", "qty", "value"):
        if key in balance_data:
            value = balance_data.get(key)
            try:
                return float(value), f"key:{key}"
            except (TypeError, ValueError):
                return 0.0, f"non_numeric:{key}"

    nested = balance_data.get("data")
    if isinstance(nested, dict):
        nested_balance, reason = _parse_balance(nested)
        return nested_balance, f"nested:{reason}"

    return 0.0, "missing_balance_key"


def run_preflight_checks(config: PolymarketCLIConfig, cli: PolymarketCLI) -> bool:
    """
    Run all pre-flight checks before live trading.
    Returns True if all critical checks pass.

    Critical checks are hard-failed. Non-critical warnings are logged with explicit codes.
    """
    cprint("\n" + "=" * 60, "yellow")
    cprint("  PRE-FLIGHT CHECKS", "yellow")
    cprint("=" * 60, "yellow")

    all_passed = True
    failures: List[Dict[str, str]] = []
    required_balance = float(config.effective_live_balance_floor_usd)

    # 1. CLI transport / health
    cprint("\n  [1/5] CLI and transport...", "white", end="")
    try:
        health = cli.get_health_status()
        transport = str(health.get("transport", "unknown"))
        if not bool(health.get("cli_status_ok", False)):
            all_passed = False
            failures.append(
                {
                    "code": "preflight.cli_unavailable",
                    "detail": str(health.get("cli_binary_check_error") or "cli unavailable"),
                }
            )
            cprint(f" FAILED ({failures[-1]['code']})", "red")
        else:
            if bool(health.get("permissions_ok", False)):
                cprint(f" OK (transport={transport})", "green")
            else:
                failures.append(
                    {
                        "code": "preflight.permissions_warning",
                        "detail": "wallet/balance visibility not confirmed",
                    }
                )
                cprint(
                    f" WARN ({failures[-1]['code']}): wallet/balance visibility not fully confirmed",
                    "yellow",
                )
    except Exception as exc:
        all_passed = False
        failures.append({"code": "preflight.health_exception", "detail": str(exc)})
        cprint(" FAILED (preflight.health_exception)", "red")

    # 2. Wallet auth works
    cprint("  [2/5] Wallet authentication...", "white", end="")
    try:
        address = cli.get_wallet_address()
    except Exception as exc:
        address = None
        all_passed = False
        failures.append({"code": "preflight.wallet_exception", "detail": str(exc)})
        cprint(" FAILED (preflight.wallet_exception)", "red")
    else:
        if address:
            masked = address[:6] + "..." + address[-4:]
            cprint(f" OK ({masked})", "green")
        else:
            all_passed = False
            failures.append(
                {
                    "code": "preflight.wallet_missing",
                    "detail": "wallet address unavailable",
                }
            )
            cprint(" FAILED (preflight.wallet_missing)", "red")

    # 3. Balance check
    cprint("  [3/5] Balance check...", "white", end="")
    try:
        balance_data = cli.get_balance()
        bal, parse_reason = _parse_balance(balance_data)
    except Exception as exc:
        all_passed = False
        failures.append({"code": "preflight.balance_exception", "detail": str(exc)})
        cprint(" FAILED (preflight.balance_exception)", "red")
    else:
        if bal >= required_balance:
            cprint(f" OK (${bal:.2f}) [parsed:{parse_reason}]", "green")
        else:
            all_passed = False
            failures.append(
                {
                    "code": "preflight.balance_too_low",
                    "detail": f"balance={bal:.2f}, minimum={required_balance:.2f}",
                }
            )
            cprint(
                f" FAILED (preflight.balance_too_low) - ${bal:.2f} < "
                f"${required_balance:.2f} minimum [parsed:{parse_reason}]",
                "red",
            )

    # 4. Cancel stale open orders
    cprint("  [4/5] Stale orders...", "white", end="")
    try:
        open_orders = cli.get_open_orders()
        if open_orders is None:
            failures.append(
                {
                    "code": "preflight.stale_orders_unknown",
                    "detail": "open orders returned None",
                }
            )
            cprint(" WARN (preflight.stale_orders_unknown)", "yellow")
        elif len(open_orders) > 0:
            cprint(f" {len(open_orders)} stale orders found - cancelling...", "yellow")
            try:
                cli.cancel_all_orders()
                cprint("         Cancelled all stale orders", "green")
            except Exception as exc:
                all_passed = False
                failures.append(
                    {
                        "code": "preflight.stale_orders_cancel_failed",
                        "detail": str(exc),
                    }
                )
                cprint("         CANCEL FAILED (preflight.stale_orders_cancel_failed)", "red")
        else:
            cprint(" OK (no stale orders)", "green")
    except Exception as exc:
        all_passed = False
        failures.append({"code": "preflight.stale_orders_exception", "detail": str(exc)})
        cprint(" FAILED (preflight.stale_orders_exception)", "red")

    # 5. Settings summary
    cprint("\n  [5/5] Settings summary:", "white")
    cprint(f"         Max Position:    ${config.live_max_position_usd:.0f}", "white")
    cprint(f"         Max Exposure:    ${config.max_total_exposure_usd:.0f}", "white")
    cprint(f"         Daily Loss Limit: ${config.daily_loss_limit_usd:.0f}", "white")
    cprint(f"         Fill Timeout:    {config.order_fill_timeout_seconds}s", "white")
    cprint(f"         Max Slippage:    {config.max_slippage_pct}%", "white")
    cprint(f"         Reserve Buffer:  ${config.live_balance_reserve_usd:.0f}", "white")
    cprint(f"         Min Balance:     ${required_balance:.0f}", "white")

    # Final verdict
    cprint("\n" + "-" * 60, "yellow")
    if failures:
        cprint("  Pre-flight failure/warn codes:", "yellow")
        for item in failures:
            cprint(f"   - {item['code']}: {item['detail']}", "yellow")

    if all_passed:
        cprint("  PRE-FLIGHT: ALL CHECKS PASSED", "green")
    else:
        cprint("  PRE-FLIGHT: FAILED - cannot start live trading", "red")
    cprint("-" * 60 + "\n", "yellow")

    return all_passed
