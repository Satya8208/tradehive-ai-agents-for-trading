"""
Trader for Polymarket CLI Agents

Trade execution via Polymarket CLI.
Supports DRY_RUN, PAPER, and LIVE execution modes.
"""

import json
import math
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from termcolor import cprint

from .cli_wrapper import PolymarketCLI
from .config import ExecutionMode, PolymarketCLIConfig, get_config
from .models import CLIMarket, TradeDecision, TradeExecution
from .risk_manager import RiskManager
from .weather_live_eligibility import WeatherLiveEligibilityGate


def _safe_round(value: float) -> float:
    try:
        return round(max(0.0, float(value or 0.0)), 4)
    except (TypeError, ValueError):
        return 0.0


class CLITrader:
    """
    Trade execution via Polymarket CLI.

    DRY_RUN: Log trade to disk, update simulated positions
    PAPER: Simulate with paper balance tracking
    LIVE: Execute via `polymarket clob create-order` / `market-order`
    """

    def __init__(
        self,
        config: Optional[PolymarketCLIConfig] = None,
        cli: Optional[PolymarketCLI] = None,
        risk_manager: Optional[RiskManager] = None,
    ):
        self.config = config or get_config()
        self.cli = cli or PolymarketCLI(self.config)
        self.risk_manager = risk_manager or RiskManager(self.config)
        self._paper_balance = self.config.paper_starting_balance
        self._trade_count = 0
        self._last_reject_reason: Optional[Dict] = None
        self._last_fill_status: Optional[Dict] = None

    @property
    def last_reject_reason(self) -> Optional[Dict]:
        return self._last_reject_reason

    @property
    def last_fill_status(self) -> Optional[Dict]:
        return self._last_fill_status

    def _is_weather_market(self, market: CLIMarket) -> bool:
        return (
            str(getattr(self.config, "market_vertical", "crypto") or "crypto").lower() == "weather"
            or str(getattr(market, "symbol", "") or "").strip().upper() == "WEATHER"
        )

    def execute_trade(
        self, decision: TradeDecision, market: CLIMarket
    ) -> Optional[TradeExecution]:
        """
        Execute a trade decision.

        1. Validate decision
        2. Check risk manager (including symbol diversification)
        3. Check order book liquidity
        4. Route to dry_run/paper/live
        5. Log execution
        6. Update positions
        """
        self._last_reject_reason = None
        self._last_fill_status = None

        size_usd = float(decision.size_usd or 0.0)
        side = str(decision.side or "").upper()
        decision_price = _safe_round(decision.price)
        if decision_price <= 0.0 or not math.isfinite(decision_price):
            self._last_reject_reason = {
                "phase": "decision",
                "reason": "invalid decision price",
                "value": decision.price,
            }
            return None
        if decision_price > 1.0:
            self._last_reject_reason = {
                "phase": "decision",
                "reason": "decision price outside binary range",
                "value": decision.price,
            }
            return None
        execution_intent_key = self.risk_manager._build_execution_intent_key(
            market_id=decision.market_id,
            side=side,
            size_usd=size_usd,
            price=decision_price,
            source=getattr(decision, "source", ""),
            execution_mode=self.config.execution_mode.value,
        )

        def _mark_intent_failed(reason: str, detail: Optional[str] = None):
            if not execution_intent_key:
                return
            note = reason if detail is None else f"{reason}: {detail}"
            self.risk_manager.mark_execution_intent_failed(execution_intent_key, note)

        def _mark_intent_completed(note: str = ""):
            if not execution_intent_key:
                return
            self.risk_manager.mark_execution_intent_completed(execution_intent_key, note or "completed")

        if not decision.should_trade:
            self._last_reject_reason = {
                "phase": "decision",
                "reason": "decision flag false",
            }
            return None

        if size_usd <= 0:
            self._last_reject_reason = {
                "phase": "decision",
                "reason": "invalid position size",
            }
            return None

        if side not in {"YES", "NO"}:
            self._last_reject_reason = {
                "phase": "decision",
                "reason": f"invalid side {side}",
            }
            return None

        if self.config.execution_mode == ExecutionMode.LIVE and self._is_weather_market(market):
            live_report = WeatherLiveEligibilityGate(self.config).evaluate()
            if not live_report.eligible:
                blockers = list(live_report.blockers or [])
                self._last_reject_reason = {
                    "phase": "live",
                    "reason": "weather_live_eligibility_failed",
                    "status": live_report.status,
                    "blockers": blockers,
                }
                _mark_intent_failed("weather_live_eligibility_failed", ", ".join(blockers[:5]))
                return None

        # Time-remaining guard — reject trades on markets about to expire.
        if (
            self.config.min_expiry_minutes > 0
            and market.end_date
            and market.time_remaining_hours < (self.config.min_expiry_minutes / 60.0)
        ):
            reason = (
                f"expires in {market.time_remaining_hours * 60:.1f}min, "
                f"need {self.config.min_expiry_minutes:.1f}min"
            )
            self._last_reject_reason = {"phase": "timing", "reason": reason}
            cprint(f"  SKIP: {market.question[:45]} -> {reason}", "yellow")
            return None

        market_symbol = self.risk_manager.normalize_symbol(
            str(getattr(market, "symbol", "")) or str(getattr(market, "question", ""))
        )
        can_trade, reason = self.risk_manager.can_trade(
            decision.market_id,
            size_usd,
            symbol=market_symbol,
            side=side,
            end_date=getattr(market, "end_date", None),
            source=getattr(decision, "source", ""),
            price=decision_price,
            execution_intent_key=execution_intent_key,
        )
        if not can_trade:
            self._last_reject_reason = {"phase": "risk", "reason": reason}
            _mark_intent_failed("risk", reason)
            cprint(f"Risk rejected: {reason}", "yellow")
            return None

        if not self._check_liquidity(size_usd, side, market):
            self._last_reject_reason = {
                "phase": "liquidity",
                "reason": "insufficient liquidity",
            }
            _mark_intent_failed("liquidity", "insufficient liquidity")
            return None

        reserved, execution_intent_key, reserve_reason = self.risk_manager.reserve_execution_intent(
            market_id=decision.market_id,
            side=side,
            size_usd=size_usd,
            price=decision_price,
            source=getattr(decision, "source", ""),
            execution_mode=self.config.execution_mode.value,
        )
        if not reserved:
            self._last_reject_reason = {
                "phase": "execution_intent",
                "reason": reserve_reason,
            }
            cprint(f"Execution intent rejected: {reserve_reason}", "yellow")
            return None

        execution = None
        mode = self.config.execution_mode
        if mode == ExecutionMode.DRY_RUN:
            execution = self._dry_run_trade(decision, market, size_usd, side)
        elif mode == ExecutionMode.PAPER:
            execution = self._paper_trade(decision, market, size_usd, side)
        elif mode == ExecutionMode.LIVE:
            try:
                execution = self._live_trade(
                    decision,
                    market,
                    size_usd,
                    side,
                    execution_intent_key=execution_intent_key,
                )
            except Exception as exc:
                self._last_reject_reason = {
                    "phase": "live",
                    "reason": "live_execution_exception",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                }
                _mark_intent_failed("live_exception", str(exc))
                cprint(f"Live execution exception: {exc}", "red")
                return None
            if self._last_fill_status:
                fill_status = self._last_fill_status.get("status")
                if fill_status not in ("filled", "filled_external"):
                    cprint(f"Live fill status: {fill_status}", "yellow")
                elif fill_status == "filled_external":
                    cprint(
                        f"Live fill observed via external-order correlation for order "
                        f"{self._last_fill_status.get('order_id', '')}",
                        "yellow",
                    )
        else:
            cprint(f"Unknown execution mode: {mode}", "red")
            self._last_reject_reason = {
                "phase": "mode",
                "reason": f"Unknown execution mode {mode}",
            }
            _mark_intent_failed("mode", f"Unknown execution mode {mode}")
            return None

        if execution is None:
            _mark_intent_failed("execution_none", f"market={decision.market_id}")
            return None

        if execution.status != "failed":
            try:
                self.risk_manager.add_position(
                    execution,
                    market.question,
                    end_date=market.end_date,
                    duration_minutes=market.duration_minutes,
                    source=getattr(decision, "source", ""),
                    symbol=market_symbol,
                )
            except Exception as e:
                if self.config.execution_mode == ExecutionMode.PAPER:
                    self._paper_balance += float(execution.size_usd or size_usd)
                self._last_reject_reason = {
                    "phase": "execution",
                    "reason": "position ledger failed",
                    "error": str(e),
                    "market_id": decision.market_id,
                }
                _mark_intent_failed("position_ledger", str(e))
                cprint(f"Position registration failed: {e}", "red")
                return None

            self.risk_manager.daily_trade_count += 1
            self._trade_count += 1
            self._save_trade_log(execution, decision, market)
            _mark_intent_completed("execution complete")

            emoji = {"dry_run": "DRY", "paper": "PAPER", "live": "LIVE"}
            mode_label = emoji.get(execution.execution_mode, "?")
            cprint(
                f"[{mode_label}] {execution.side} on '{market.question[:45]}' "
                f"${execution.size_usd:.2f} @ {execution.price:.4f} "
                f"({execution.status})",
                "green"
                if execution.status in ("simulated", "paper_filled", "filled")
                else "yellow",
            )
            return execution

        self._last_reject_reason = {
            "phase": "execution",
            "reason": "execution failed",
            "mode": self.config.execution_mode.value,
            "market_id": decision.market_id,
        }
        _mark_intent_failed("execution_failed", str(self._last_reject_reason))
        return execution

    def _dry_run_trade(
        self,
        decision: TradeDecision,
        market: CLIMarket,
        size_usd: float,
        side: str,
    ) -> TradeExecution:
        """Log only. No balance impact."""
        token_id = (
            market.yes_token_id if side == "YES" else market.no_token_id
        )
        return TradeExecution(
            trade_id=str(uuid.uuid4())[:8],
            market_id=decision.market_id,
            token_id=token_id,
            side=side,
            size_usd=size_usd,
            price=decision.price,
            status="simulated",
            execution_mode="dry_run",
            timestamp=datetime.utcnow(),
            requested_size_usd=size_usd,
            submitted_shares=self._paper_size_to_shares(size_usd, decision.price),
            submitted_notional_usd=size_usd,
            filled_shares=self._paper_size_to_shares(size_usd, decision.price),
            filled_notional_usd=size_usd,
            decision_price=decision.price,
            placed_price=decision.price,
            fill_status_source="dry_run",
            prediction_path=str(getattr(decision, "prediction_path", "") or ""),
        )

    def _paper_trade(
        self,
        decision: TradeDecision,
        market: CLIMarket,
        size_usd: float,
        side: str,
    ) -> Optional[TradeExecution]:
        """Simulate with paper balance."""
        if self._paper_balance < size_usd:
            self._last_reject_reason = {
                "phase": "paper",
                "reason": "insufficient paper balance",
            }
            cprint(f"Paper balance insufficient: ${self._paper_balance:.2f}", "yellow")
            return None

        token_id = (
            market.yes_token_id if side == "YES" else market.no_token_id
        )
        self._paper_balance -= size_usd

        return TradeExecution(
            trade_id=str(uuid.uuid4())[:8],
            market_id=decision.market_id,
            token_id=token_id,
            side=side,
            size_usd=size_usd,
            price=decision.price,
            status="paper_filled",
            execution_mode="paper",
            timestamp=datetime.utcnow(),
            fees=size_usd * 0.02,  # Estimated 2% fee
            requested_size_usd=size_usd,
            submitted_shares=self._paper_size_to_shares(size_usd, decision.price),
            submitted_notional_usd=size_usd,
            filled_shares=self._paper_size_to_shares(size_usd, decision.price),
            filled_notional_usd=size_usd,
            decision_price=decision.price,
            placed_price=decision.price,
            fill_status_source="paper_fill",
            prediction_path=str(getattr(decision, "prediction_path", "") or ""),
        )

    def _live_trade(
        self,
        decision: TradeDecision,
        market: CLIMarket,
        size_usd: float,
        side: str,
        execution_intent_key: str = "",
    ) -> Optional[TradeExecution]:
        """Execute real trade via `polymarket clob create-order` / `market-order`."""
        token_id = market.yes_token_id if side == "YES" else market.no_token_id

        # Re-fetch fresh price at order time (analysis price may be stale).
        raw_mid = self.cli.get_midpoint(token_id)
        fresh_price = None
        if isinstance(raw_mid, dict):
            fresh_price = self._safe_float(raw_mid.get("mid"))
            if fresh_price is None:
                fresh_price = self._safe_float(raw_mid.get("price"))
        else:
            fresh_price = self._safe_float(raw_mid)

        requested_size_usd = float(size_usd or 0.0)
        original_decision_price = _safe_round(decision.price)
        if not original_decision_price:
            self._last_reject_reason = {"phase": "live", "reason": "invalid decision price"}
            return None
        decision_price = original_decision_price

        if fresh_price and fresh_price > 0:
            stale_price = decision_price
            decision_price = round(
                fresh_price,
                2,
            )
            if stale_price > 0:
                move = abs(decision_price - stale_price) / stale_price
                if move > 0.03:
                    cprint(
                        f"  Price moved: {stale_price:.4f} -> {decision_price:.4f} "
                        f"({move * 100:+.1f}%)",
                        "yellow",
                    )

        if decision_price <= 0:
            self._last_reject_reason = {"phase": "live", "reason": "invalid normalized price"}
            return None

        # Clamp to legal CLOB bounds before submitting.
        decision_price = max(0.0001, min(0.9999, decision_price))

        raw_shares = round(self._paper_size_to_shares(requested_size_usd, decision_price), 2)
        shares = raw_shares
        if 0 < shares < 5:
            shares = 5.0

        if shares <= 0:
            self._last_reject_reason = {"phase": "live", "reason": "zero shares after price normalization"}
            return None

        submitted_notional_usd = round(shares * decision_price, 4)
        remaining_budget = max(
            0.0,
            float(self.config.max_total_exposure_usd)
            - float(self.risk_manager.total_exposure)
            - float(self.risk_manager.pending_live_notional),
        )
        live_position_cap = float(self.config.effective_live_max_position_usd)

        balance_payload = None
        live_balance = None
        balance_reason = ""
        try:
            balance_payload = self.cli.get_balance()
            live_balance, balance_reason = self._extract_balance_value(balance_payload)
        except Exception as exc:
            balance_reason = f"balance_exception:{exc.__class__.__name__}"

        if live_balance is None:
            reason = f"unable to verify live balance ({balance_reason or 'unknown'})"
            self._last_reject_reason = {"phase": "live", "reason": reason}
            if execution_intent_key:
                self.risk_manager.mark_execution_intent_failed(execution_intent_key, reason)
            return None

        balance_guard = self.config.live_available_balance_guard_usd(live_balance)
        share_floor_violations = []
        tolerance = 1e-6
        if submitted_notional_usd - requested_size_usd > tolerance:
            share_floor_violations.append(
                f"requested={requested_size_usd:.2f}, actual={submitted_notional_usd:.2f}"
            )
        if submitted_notional_usd - remaining_budget > tolerance:
            share_floor_violations.append(
                f"remaining_budget={remaining_budget:.2f}, actual={submitted_notional_usd:.2f}"
            )
        if submitted_notional_usd - live_position_cap > tolerance:
            share_floor_violations.append(
                f"max_position={live_position_cap:.2f}, actual={submitted_notional_usd:.2f}"
            )
        if submitted_notional_usd - balance_guard > tolerance:
            share_floor_violations.append(
                f"balance_guard={balance_guard:.2f}, actual={submitted_notional_usd:.2f}"
            )
        if share_floor_violations:
            reason = "min share floor exceeds " + "; ".join(share_floor_violations)
            self._last_reject_reason = {
                "phase": "live",
                "reason": "min_share_floor_exceeds_budget",
                "detail": reason,
                "raw_shares": raw_shares,
                "submitted_shares": shares,
                "submitted_notional_usd": submitted_notional_usd,
            }
            if execution_intent_key:
                self.risk_manager.mark_execution_intent_failed(execution_intent_key, reason)
            return None

        cprint(
            f"Executing LIVE order: {side} {shares:.2f} shares @ ${decision_price:.2f}...",
            "yellow",
        )

        prediction_path = str(getattr(decision, "prediction_path", "") or "")
        order_type = "FOK" if prediction_path.startswith("arb_basket|") else "GTC"
        try:
            result = self.cli.create_limit_order(
                token_id=token_id,
                side="buy",
                price=decision_price,
                size=shares,
                order_type=order_type,
            )
        except Exception as exc:
            self._last_reject_reason = {
                "phase": "live",
                "reason": "order_submit_exception",
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            }
            cprint(f"Live order submission exception: {exc}", "red")
            return TradeExecution(
                trade_id=str(uuid.uuid4())[:8],
                market_id=decision.market_id,
                token_id=token_id,
                side=side,
                size_usd=0.0,
                price=decision.price,
                status="failed",
                execution_mode="live",
                timestamp=datetime.utcnow(),
                requested_size_usd=requested_size_usd,
                submitted_shares=shares,
                submitted_notional_usd=submitted_notional_usd,
                decision_price=original_decision_price,
                placed_price=decision_price,
                prediction_path=str(getattr(decision, "prediction_path", "") or ""),
            )
        if result is None:
            self._last_reject_reason = {"phase": "live", "reason": "order submit failed"}
            cprint("Live order failed!", "red")
            if execution_intent_key:
                self.risk_manager.mark_execution_intent_failed(
                    execution_intent_key,
                    "order submit failed",
                )
            return TradeExecution(
                trade_id=str(uuid.uuid4())[:8],
                market_id=decision.market_id,
                token_id=token_id,
                side=side,
                size_usd=0.0,
                price=decision.price,
                status="failed",
                execution_mode="live",
                timestamp=datetime.utcnow(),
                requested_size_usd=requested_size_usd,
                submitted_shares=shares,
                submitted_notional_usd=submitted_notional_usd,
                decision_price=original_decision_price,
                placed_price=decision_price,
                prediction_path=str(getattr(decision, "prediction_path", "") or ""),
            )

        order_id = str(result.get("orderID", result.get("id", ""))).strip()
        if not order_id:
            self._last_reject_reason = {"phase": "live", "reason": "missing order id"}
            if execution_intent_key:
                self.risk_manager.mark_execution_intent_failed(
                    execution_intent_key,
                    "missing order id",
                )
            return TradeExecution(
                trade_id=str(uuid.uuid4())[:8],
                market_id=decision.market_id,
                token_id=token_id,
                side=side,
                size_usd=0.0,
                price=decision.price,
                status="failed",
                execution_mode="live",
                timestamp=datetime.utcnow(),
                requested_size_usd=requested_size_usd,
                submitted_shares=shares,
                submitted_notional_usd=submitted_notional_usd,
                decision_price=original_decision_price,
                placed_price=decision_price,
                prediction_path=str(getattr(decision, "prediction_path", "") or ""),
            )

        self.risk_manager.register_live_order(
            order_id=order_id,
            market_id=decision.market_id,
            token_id=token_id,
            side=side,
            requested_size_usd=requested_size_usd,
            submitted_shares=shares,
            submitted_notional_usd=submitted_notional_usd,
            decision_price=original_decision_price,
            placed_price=decision_price,
            execution_mode=self.config.execution_mode.value,
            prediction_path=str(getattr(decision, "prediction_path", "") or ""),
        )

        if execution_intent_key:
            self.risk_manager.mark_execution_intent_submitted(
                execution_intent_key,
                order_id=order_id,
                note="submitted to clob",
            )

        fill = self._wait_for_fill(
                order_id=order_id,
                token_id=token_id,
                market_id=decision.market_id,
                timeout=self.config.order_fill_timeout_seconds,
                expected_size=shares,
                expected_price=decision_price,
            )
        self._last_fill_status = fill
        self.risk_manager.apply_live_order_result(order_id, fill)

        if not fill or fill.get("status") not in ("filled", "filled_external"):
            reason = "not filled"
            if fill and isinstance(fill, dict):
                reason = fill.get("status", reason)
                if fill.get("reason"):
                    reason = f"{reason}: {fill['reason']}"
            self._last_reject_reason = {"phase": "live", "reason": reason}
            if execution_intent_key:
                self.risk_manager.mark_execution_intent_failed(
                    execution_intent_key,
                    reason,
                )
            return None

        fill_price = fill.get("fill_price", decision.price)
        fill_fees = fill.get("fees", 0.0)
        filled_shares = self._safe_float(fill.get("fill_size", shares)) or shares
        filled_notional_usd = round(filled_shares * float(fill_price), 4) if fill_price else submitted_notional_usd

        if decision_price > 0 and fill_price is not None:
            slippage_pct = abs(float(fill_price) - decision_price) / decision_price * 100
            if slippage_pct > self.config.max_slippage_pct:
                cprint(
                    f"  SLIPPAGE WARNING: {slippage_pct:.1f}% "
                    f"(expected {decision_price:.4f}, got {fill_price:.4f})",
                    "yellow",
                )

        return TradeExecution(
            trade_id=str(uuid.uuid4())[:8],
            market_id=decision.market_id,
            token_id=token_id,
            side=side,
            size_usd=filled_notional_usd,
            price=float(fill_price),
            status="filled",
            execution_mode="live",
            timestamp=datetime.utcnow(),
            order_id=order_id,
            fees=fill_fees or 0.0,
            requested_size_usd=requested_size_usd,
            submitted_shares=shares,
            submitted_notional_usd=submitted_notional_usd,
            filled_shares=filled_shares,
            filled_notional_usd=filled_notional_usd,
            decision_price=original_decision_price,
            placed_price=decision_price,
            fill_status_source=str(fill.get("source", "")),
            prediction_path=str(getattr(decision, "prediction_path", "") or ""),
        )

    @staticmethod
    def _paper_size_to_shares(size_usd: float, price: float) -> float:
        if not price or price <= 0:
            return 0.0
        return size_usd / price

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        try:
            parsed = float(value)
            if parsed != parsed:  # NaN guard
                return None
            return parsed
        except (TypeError, ValueError):
            return None

    @classmethod
    def _extract_balance_value(cls, balance_data) -> tuple[Optional[float], str]:
        if balance_data is None:
            return None, "missing_balance_payload"
        if isinstance(balance_data, (int, float)):
            parsed = cls._safe_float(balance_data)
            return parsed, "direct_number" if parsed is not None else "invalid_number"
        if not isinstance(balance_data, dict):
            return None, f"unexpected_type:{type(balance_data).__name__}"

        for key in ("balance", "amount", "qty", "value"):
            if key in balance_data:
                parsed = cls._safe_float(balance_data.get(key))
                if parsed is not None:
                    return parsed, key

        nested = balance_data.get("data")
        if isinstance(nested, dict):
            return cls._extract_balance_value(nested)
        return None, "missing_balance_key"

    @staticmethod
    def _normalize_id(value) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        if text.lower().startswith("0x"):
            try:
                return str(int(text, 16))
            except ValueError:
                return ""
        return text

    def _wait_for_fill(
        self,
        order_id: str,
        token_id: str,
        market_id: Optional[str] = None,
        timeout: int = 30,
        expected_size: Optional[float] = None,
        expected_price: Optional[float] = None,
    ) -> Optional[Dict]:
        """
        Deterministic fill helper with explicit evidence path.
        """
        return self._wait_for_fill_deterministic(
            order_id=order_id,
            token_id=token_id,
            market_id=market_id,
            timeout=timeout,
            expected_size=expected_size,
            expected_price=expected_price,
        )

    def _wait_for_fill_deterministic(
        self,
        order_id: str,
        token_id: str,
        market_id: Optional[str] = None,
        timeout: int = 30,
        expected_size: Optional[float] = None,
        expected_price: Optional[float] = None,
    ) -> Optional[Dict]:
        """
        Deterministic fill verifier with explicit queue/order evidence.
        """
        if not order_id:
            return {"status": "invalid", "error": "missing order id"}

        timeout_seconds = max(0, int(timeout))
        poll_interval = 2
        normalized_order_id = self._normalize_id(order_id)
        normalized_token_id = self._normalize_id(token_id)
        normalized_market_id = self._normalize_id(market_id) or None
        start_ts = time.monotonic()

        def _load_open_orders(scope: Optional[str]) -> List[Dict]:
            try:
                orders = self.cli.get_open_orders(scope)
            except Exception as exc:
                cprint(f"Failed to load open orders for fill polling: {exc}", "yellow")
                return []
            return orders if isinstance(orders, list) else []

        def _load_trades(scope: Optional[str]) -> List[Dict]:
            try:
                trades = self.cli.get_trades(scope)
            except Exception as exc:
                cprint(f"Failed to load trades for fill polling: {exc}", "yellow")
                return []
            return trades if isinstance(trades, list) else []

        def _order_state(scope: Optional[str]) -> tuple[bool, List[Dict]]:
            orders = _load_open_orders(scope)
            if not orders and scope:
                orders = _load_open_orders(None)

            order_still_open = any(
                self._normalize_id(
                    o.get("id", o.get("orderID", o.get("order_id", "")))
                ) == normalized_order_id
                for o in orders
            )
            token_open_orders = [
                o
                for o in orders
                if self._normalize_id(o.get("token_id", o.get("asset_id", ""))) == normalized_token_id
            ]
            return order_still_open, token_open_orders

        normalized_expected_size = self._safe_float(expected_size)
        normalized_expected_price = self._safe_float(expected_price)
        normalized_market = self._normalize_id(market_id)

        def _is_size_plausible(raw_size: Optional[float]) -> bool:
            if normalized_expected_size is None or normalized_expected_size <= 0:
                return True
            fill_size = self._safe_float(raw_size)
            if fill_size is None:
                return False
            if fill_size <= 0:
                return False
            # Require observed size to be meaningfully close to intent size unless explicit
            # smaller fills could be valid. This filter cuts false positives from unrelated token activity.
            min_ratio = 0.25
            max_ratio = 2.5
            ratio = fill_size / normalized_expected_size
            return min_ratio <= ratio <= max_ratio

        def _is_price_plausible(raw_price: Optional[float]) -> bool:
            if normalized_expected_price is None or normalized_expected_price <= 0:
                return True
            fill_price = self._safe_float(raw_price)
            if fill_price is None or fill_price <= 0:
                return False
            # Keep a very wide spread for market volatility/slippage, but reject obvious outliers.
            spread = abs(fill_price - normalized_expected_price) / normalized_expected_price
            return spread <= 0.80

        def _find_fill(trades: List[Dict]) -> Optional[Dict]:
            for t in trades:
                trade_order_id = self._normalize_id(
                    t.get("orderID", t.get("order_id", t.get("id", "")))
                )
                trade_token = self._normalize_id(t.get("token_id", t.get("tokenId", "")))
                if trade_order_id and trade_order_id == normalized_order_id:
                    trade_market = self._normalize_id(t.get("market_id", t.get("market", t.get("condition_id", ""))))
                    if normalized_market and trade_market and trade_market != normalized_market:
                        continue
                    return {
                        "status": "filled",
                        "fill_price": self._safe_float(t.get("price", 0.0)) or 0.0,
                        "fill_size": self._safe_float(t.get("size", t.get("amount", 0.0)))
                        or 0.0,
                        "fees": self._safe_float(t.get("fee", t.get("fees", 0.0))) or 0.0,
                        "order_id": order_id,
                        "market_id": market_id,
                        "source": "order_id_match",
                    }
                if trade_token and trade_token == normalized_token_id:
                    trade_market = self._normalize_id(t.get("market_id", t.get("market", t.get("condition_id", ""))))
                    if normalized_market and trade_market and trade_market != normalized_market:
                        continue
                    trade_size = self._safe_float(t.get("size", t.get("amount", 0.0)))
                    if not _is_size_plausible(trade_size):
                        continue
                    if not _is_price_plausible(t.get("price", t.get("p", None))):
                        continue
                    return {
                        "status": "filled_external",
                        "fill_price": self._safe_float(t.get("price", 0.0)) or 0.0,
                        "fill_size": self._safe_float(t.get("size", t.get("amount", 0.0)))
                        or 0.0,
                        "fees": self._safe_float(t.get("fee", t.get("fees", 0.0))) or 0.0,
                        "order_id": order_id,
                        "market_id": market_id,
                        "source": "external_token_match",
                    }
            return None

        disappeared_cycles = 0
        while True:
            elapsed = int(time.monotonic() - start_ts)
            if elapsed >= timeout_seconds:
                break

            time.sleep(min(poll_interval, max(1, timeout_seconds - elapsed)))
            elapsed = int(time.monotonic() - start_ts)

            order_still_open, token_open_orders = _order_state(normalized_market_id)
            if order_still_open:
                continue

            trades = _load_trades(normalized_market_id)
            if not trades and normalized_market_id:
                trades = _load_trades(None)

            fill = _find_fill(trades)
            if fill is not None:
                fill["elapsed"] = elapsed
                return fill

            if token_open_orders:
                queue_sample = token_open_orders[0]
                return {
                    "status": "not_filled_external_queue",
                    "fill_price": self._safe_float(queue_sample.get("price", 0.0)) or 0.0,
                    "fill_size": 0.0,
                    "fees": 0.0,
                    "order_id": order_id,
                    "market_id": market_id,
                    "elapsed": elapsed,
                    "source": "open_queue",
                    "reason": "order id disappeared but token still on book",
                }

            disappeared_cycles += 1
            if disappeared_cycles < 2:
                # Give one more evidence window before concluding no fill.
                continue

            return {
                "status": "not_filled",
                "order_id": order_id,
                "market_id": market_id,
                "elapsed": elapsed,
                "reason": "order disappeared with no trade evidence",
            }

        order_still_open, token_open_orders = _order_state(normalized_market_id)
        final_elapsed = int(time.monotonic() - start_ts)

        if order_still_open:
            cprint(f"  Fill timeout ({timeout}s) - cancelling order {order_id}", "yellow")
            cancel_result = self.cli.cancel_order(order_id)
            if cancel_result is None:
                return {
                    "status": "timeout_cancel_failed",
                    "order_id": order_id,
                    "market_id": market_id,
                    "elapsed": final_elapsed,
                    "reason": "cancel failed",
                }
            # Cancel succeeded; re-check fills to avoid race false negatives.
            post_cancel_trades = _load_trades(normalized_market_id)
            if not post_cancel_trades and normalized_market_id:
                post_cancel_trades = _load_trades(None)
            post_cancel_fill = _find_fill(post_cancel_trades)
            if post_cancel_fill is not None:
                post_cancel_fill["elapsed"] = final_elapsed
                return post_cancel_fill

            post_cancel_open, post_cancel_token_orders = _order_state(normalized_market_id)
            if post_cancel_open:
                queue_sample = post_cancel_token_orders[0] if post_cancel_token_orders else {}
                return {
                    "status": "open_after_cancel",
                    "fill_price": self._safe_float(queue_sample.get("price", 0.0)) or 0.0,
                    "fill_size": 0.0,
                    "fees": 0.0,
                    "order_id": order_id,
                    "market_id": market_id,
                    "elapsed": final_elapsed,
                    "source": "post_cancel_queue",
                    "reason": "cancel succeeded but order still present on open book",
                }

            return {
                "status": "timeout_cancelled",
                "order_id": order_id,
                "market_id": market_id,
                "elapsed": final_elapsed,
            }

        if token_open_orders:
            queue_sample = token_open_orders[0]
            return {
                "status": "not_filled_external_queue",
                "fill_price": self._safe_float(queue_sample.get("price", 0.0)) or 0.0,
                "fill_size": 0.0,
                "fees": 0.0,
                "order_id": order_id,
                "market_id": market_id,
                "elapsed": final_elapsed,
                "source": "open_queue",
                "reason": "order vanished after timeout with open token-level queue",
            }

        final_trades = _load_trades(normalized_market_id)
        if not final_trades and normalized_market_id:
            final_trades = _load_trades(None)
        fill = _find_fill(final_trades)
        if fill is not None:
            fill["elapsed"] = final_elapsed
            return fill

        return {
            "status": "not_filled_unknown",
            "order_id": order_id,
            "market_id": market_id,
            "elapsed": final_elapsed,
            "reason": "order vanished after timeout with no trade evidence",
        }

    def _check_liquidity(self, size_usd: float, side: str, market: CLIMarket) -> bool:
        """
        Check order book has sufficient depth for our trade size.
        Returns False if book is too thin (skips the trade).
        """
        token_id = market.yes_token_id if side == "YES" else market.no_token_id
        book = self.cli.get_order_book(token_id)
        if not book:
            return True

        asks = book.get("asks", []) if isinstance(book, dict) else []
        if not asks:
            return True

        available = 0.0
        for level in asks[:5]:
            try:
                size = float(level.get("size", level.get("s", 0)))
                price = float(level.get("price", level.get("p", 0)))
                available += size * (price if price > 0 else 1.0)
            except (TypeError, ValueError):
                continue

        if available > 0 and available < size_usd * 0.5:
            cprint(
                f"  THIN BOOK: ${available:.0f} available vs "
                f"${size_usd:.0f} wanted ",
                "yellow",
            )
            return False
        return True

    def _save_trade_log(
        self,
        execution: TradeExecution,
        decision: TradeDecision = None,
        market: CLIMarket = None,
    ):
        """Append trade to daily JSONL file with decision + market context."""
        self.config.ensure_dirs()
        date_str = execution.timestamp.strftime("%Y%m%d")
        log_file = self.config.trades_dir / f"trades_{date_str}.jsonl"

        data = execution.to_dict()
        if decision:
            data["source"] = decision.source
            data["reason"] = decision.reason
            data["confidence"] = decision.confidence
            data["prediction_path"] = str(getattr(decision, "prediction_path", "") or data.get("prediction_path", ""))
        if market:
            data["symbol"] = market.symbol
            data["question"] = market.question
            data["duration_minutes"] = market.duration_minutes
            data["time_remaining_hours"] = round(market.time_remaining_hours, 2)
            data["market_type"] = market.market_type

        try:
            with open(log_file, "a") as f:
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            cprint(f"Failed to save trade log: {e}", "red")

    def close_position(
        self, market_id: str, close_price: float, reason: str = "exit_signal"
    ) -> Optional[float]:
        """
        Close a position. Returns realized PnL.
        In paper mode, returns capital + PnL to paper balance.
        In live mode, submits a sell order and waits for fill.
        """
        if market_id not in self.risk_manager.positions:
            return None

        pos = self.risk_manager.positions[market_id]
        if self.config.execution_mode == ExecutionMode.LIVE:
            if pos.entry_price <= 0:
                cprint(
                    f"  Cannot close: invalid entry price {pos.entry_price:.4f} for {market_id}",
                    "red",
                )
                return None

            shares = round(float(getattr(pos, "shares", 0.0) or 0.0), 2)
            if shares <= 0:
                cprint(f"  Cannot close: zero shares for {market_id}", "red")
                return None

            cprint(
                f"  Submitting LIVE exit: sell {shares:.2f} shares of "
                f"{pos.question[:40]}...",
                "yellow",
            )
            try:
                result = self.cli.create_market_order(pos.token_id, "sell", shares)
            except Exception as exc:
                cprint(
                    f"  EXIT ORDER EXCEPTION: {exc}",
                    "red",
                )
                self._last_reject_reason = {
                    "phase": "live_close",
                    "reason": "order_submit_exception",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                }
                return None

            if result is None:
                cprint(
                    "  EXIT ORDER FAILED - position stays tracked, retry next cycle",
                    "red",
                )
                self._last_reject_reason = {
                    "phase": "live_close",
                    "reason": "exit_order_submit_failed",
                }
                return None

            exit_order_id = result.get("orderID", result.get("id", ""))
            if not exit_order_id:
                cprint(
                    "  EXIT ORDER FAILED - missing exit order id",
                    "red",
                )
                return None

            requested_exit_notional = round(shares * max(close_price, 0.0), 4)
            self.risk_manager.register_live_order(
                order_id=str(exit_order_id),
                market_id=market_id,
                token_id=pos.token_id,
                side=f"CLOSE_{pos.side}",
                requested_size_usd=requested_exit_notional,
                submitted_shares=shares,
                submitted_notional_usd=requested_exit_notional,
                decision_price=close_price,
                placed_price=close_price,
                execution_mode=self.config.execution_mode.value,
                prediction_path="",
                intent_type="exit",
            )

            fill = self._wait_for_fill(
                exit_order_id,
                pos.token_id,
                market_id=market_id,
                timeout=60,
                expected_size=shares,
                expected_price=close_price,
            )
            self.risk_manager.apply_live_order_result(str(exit_order_id), fill)
            if not fill or fill.get("status") not in ("filled", "filled_external"):
                cprint(
                    "  EXIT NOT FILLED - position stays tracked, retry next cycle",
                    "red",
                )
                return None
            actual_close = fill.get("fill_price")
            parsed_fill_price = self._safe_float(actual_close)
            if parsed_fill_price is not None:
                close_price = float(parsed_fill_price)
            fill_size = self._safe_float(fill.get("fill_size", shares)) or shares
            filled_notional_usd = round(fill_size * close_price, 4)
        else:
            fill_size = float(getattr(pos, "shares", 0.0) or 0.0)
            filled_notional_usd = round(fill_size * close_price, 4)

        pos.update_price(close_price)
        pnl = pos.unrealized_pnl
        returned_value = pos.market_value

        if self.config.execution_mode == ExecutionMode.PAPER:
            self._paper_balance += returned_value

        close_execution = TradeExecution(
            trade_id=str(uuid.uuid4())[:8],
            market_id=market_id,
            token_id=pos.token_id,
            side=f"CLOSE_{pos.side}",
            size_usd=pos.size_usd,
            price=close_price,
            status="closed",
            execution_mode=self.config.execution_mode.value,
            timestamp=datetime.utcnow(),
            requested_size_usd=filled_notional_usd,
            submitted_shares=fill_size,
            submitted_notional_usd=filled_notional_usd,
            filled_shares=fill_size,
            filled_notional_usd=filled_notional_usd,
            decision_price=close_price,
            placed_price=close_price,
            fill_status_source="close_position",
            prediction_path="",
        )
        self._save_trade_log(close_execution)

        realized_pnl = self.risk_manager.close_position(market_id, close_price)
        color = "green" if realized_pnl >= 0 else "red"
        cprint(
            f"  CLOSED: '{pos.question[:45]}' | PnL: ${realized_pnl:+.2f} "
            f"({pos.return_pct:+.1f}%) | Reason: {reason}",
            color,
        )
        return realized_pnl

    def get_paper_balance(self) -> float:
        """Get current paper trading balance."""
        return self._paper_balance

    def get_trade_count(self) -> int:
        """Total trades executed this session."""
        return self._trade_count

    def get_summary(self) -> str:
        """Summary of trading session."""
        mode = self.config.execution_mode.value.upper()
        lines = [
            f"Trader [{mode}]:",
            f"  Trades: {self._trade_count}",
        ]
        if self.config.execution_mode == ExecutionMode.PAPER:
            lines.append(f"  Paper Balance: ${self._paper_balance:.2f}")
        return "\n".join(lines)


if __name__ == "__main__":
    trader = CLITrader()
    print(trader.get_summary())
