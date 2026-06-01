"""
Risk Manager for Polymarket CLI Agents

Circuit breakers, position tracking, daily limits.
Position price refresh, resolution detection, and exit logic.
Works in all modes including dry run.
"""

import json
import math
import os
import tempfile
import time
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from termcolor import cprint

from .config import PolymarketCLIConfig, get_config, get_schema_version
from .models import Position, TradeExecution

STATE_RESOLVED_STALE_SECONDS = 12 * 60 * 60
STATE_EXECUTION_INTENT_TTL_SECONDS = 12 * 60 * 60
STATE_EXECUTION_INTENT_COMPLETED_TTL_SECONDS = 7 * 24 * 60 * 60
STATE_LIVE_ORDER_COMPLETED_TTL_SECONDS = 7 * 24 * 60 * 60


def _safe_float(value, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        if not math.isfinite(parsed):
            return default
        return parsed
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        parsed = int(value)
        if parsed < 0:
            return default
        return parsed
    except (TypeError, ValueError):
        return default


class RiskManager:
    """
    Risk management for the Polymarket CLI trading system.

    Tracks open positions, daily P&L, total exposure, trade count.
    """

    def __init__(self, config: Optional[PolymarketCLIConfig] = None):
        self.config = config or get_config()
        self.positions: Dict[str, Position] = {}
        self.execution_intents: Dict[str, Dict] = {}
        self.live_orders: Dict[str, Dict] = {}
        self.daily_pnl: float = 0.0
        self.daily_trade_count: int = 0
        self._halted: bool = False
        self._halt_reason: str = ""
        self._halt_reason_code: str = ""
        self._today: str = date.today().isoformat()
        self._expiry_stats: Dict[str, Dict] = {}
        self._symbol_stats: Dict[str, Dict] = {}
        self._source_stats: Dict[str, Dict] = {}
        self._state_schema_version: int = get_schema_version()
        self._unresolved_closed_markets: Dict[str, float] = {}
        self._invalid_state_rows: int = 0

        self._load_state()

    # ------------------------------------------------------------------ utils

    @staticmethod
    def _normalize_symbol(value: str) -> str:
        parsed = (value or "").strip().upper()
        return parsed if parsed else "OTHER"

    def normalize_symbol(self, value: str) -> str:
        """Public symbol normalization for callers that need stable portfolio keys."""
        return self._normalize_symbol(value)

    @staticmethod
    def _is_valid_side(side: str) -> bool:
        return str(side).upper() in {"YES", "NO"}

    @staticmethod
    def _to_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    @staticmethod
    def _safe_bool_flag(value) -> Optional[bool]:
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on", "winner", "win"}:
            return True
        if text in {"0", "false", "no", "off", "loser", "loss"}:
            return False
        return None

    @staticmethod
    def _to_float(value, default: float = 0.0) -> float:
        try:
            parsed = float(value)
            if not math.isfinite(parsed):
                return default
            return parsed
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_timestamp(value, default: Optional[float] = None) -> Optional[float]:
        if value is None:
            return default
        if isinstance(value, (int, float)):
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                return default
            return parsed if math.isfinite(parsed) else default
        if isinstance(value, datetime):
            return value.timestamp()
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value).timestamp()
            except Exception:
                return default
        return default

    @staticmethod
    def _normalize_execution_side(side: str) -> str:
        return str(side or "").strip().upper()

    @staticmethod
    def _build_execution_intent_key(
        market_id: str,
        side: str,
        size_usd: float,
        price: float,
        source: str = "",
        execution_mode: str = "",
    ) -> str:
        market = str(market_id or "unknown").strip()
        normalized_side = RiskManager._normalize_execution_side(side)
        return (
            f"exec:{str(execution_mode or 'unknown').lower()}:"
            f"{str(source or 'unknown').lower()}:"
            f"{market}:{normalized_side}:"
            f"{_safe_float(size_usd, 0.0):.2f}:{_safe_float(price, 0.0):.4f}"
        )

    @staticmethod
    def _normalize_token_id(value) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        if text.startswith("0x") or text.startswith("0X"):
            try:
                return str(int(text, 16))
            except ValueError:
                return ""
        text = text.replace(" ", "")
        # Guard against accidental float/string noise.
        if "." in text:
            text = text.split(".")[0]
        if text.isdigit():
            return text
        return ""

    @staticmethod
    def _normalize_order_id(value) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        if text.lower().startswith("0x"):
            try:
                return str(int(text, 16))
            except ValueError:
                return text
        if "." in text:
            text = text.split(".", 1)[0]
        return text

    @staticmethod
    def _safe_positive_float(value, default: Optional[float] = None) -> Optional[float]:
        parsed = _safe_float(value, default if default is not None else float("nan"))
        if parsed is None:
            return default
        if parsed < 0.0:
            return default
        if math.isfinite(parsed):
            return parsed
        return default

    def _mark_unresolved_closed_market(
        self,
        market_id: str,
        now_ts: Optional[float] = None,
    ) -> float:
        now_ts = float(now_ts or time.time())
        marker = self._unresolved_closed_markets.get(market_id)
        if marker is None:
            self._unresolved_closed_markets[market_id] = now_ts
            self._save_state()
            return now_ts
        return _safe_float(marker, now_ts)

    @staticmethod
    def _canonical_outcome(value) -> str:
        if value is None:
            return ""
        text = str(value).strip().lower()
        if not text:
            return ""
        if text in {"yes", "y", "true", "1", "win", "winner"}:
            return "YES"
        if text in {"no", "n", "false", "0", "loss", "loser"}:
            return "NO"
        return ""

    @staticmethod
    def _token_outcome(token: Dict) -> str:
        if not isinstance(token, dict):
            return ""
        for key in ("outcome", "outcomeName", "name", "result"):
            value = RiskManager._canonical_outcome(token.get(key))
            if value:
                return value
        return ""

    def _infer_resolved_outcome(self, market_data: Dict) -> Tuple[str, str]:
        """
        Infer resolved outcome from heterogeneous API payload shapes.
        Returns (outcome, source).
        """
        tokens = market_data.get("tokens", [])
        if not isinstance(tokens, list):
            tokens = []

        for token in tokens:
            if not isinstance(token, dict):
                continue
            winner_flag = token.get("winner", token.get("isWinner"))
            if self._safe_bool_flag(winner_flag) is True:
                outcome = self._token_outcome(token)
                if outcome:
                    return outcome, "token_winner_flag"

        for field in ("winningOutcome", "winnerOutcome", "outcome", "result"):
            outcome = self._canonical_outcome(market_data.get(field))
            if outcome:
                return outcome, f"market_{field}"

        winner_token_id = market_data.get("winnerTokenId", market_data.get("winningTokenId"))
        if winner_token_id:
            target = self._normalize_token_id(winner_token_id)
            if target:
                for token in tokens:
                    if not isinstance(token, dict):
                        continue
                    token_id = self._normalize_token_id(
                        token.get("token_id", token.get("tokenId", token.get("id", "")))
                    )
                    if token_id and token_id == target:
                        outcome = self._token_outcome(token)
                        if outcome:
                            return outcome, "token_id_match"

        winner_index = market_data.get("winnerIndex")
        if winner_index is not None:
            try:
                winner_position = int(winner_index)
                if 0 <= winner_position < len(tokens):
                    token = tokens[winner_position]
                    outcome = self._token_outcome(token)
                    if outcome:
                        return outcome, "winner_index"
            except (TypeError, ValueError):
                pass

        return "", "unresolved"

    def _invariant_position(self, pos: Position) -> bool:
        if not isinstance(pos.market_id, str) or not pos.market_id.strip():
            return False
        normalized_token_id = self._normalize_token_id(pos.token_id)
        if not normalized_token_id:
            return False
        pos.token_id = normalized_token_id

        if pos.size_usd < 0 or pos.entry_price < 0 or pos.current_price < 0:
            return False
        if not math.isfinite(pos.size_usd) or not math.isfinite(pos.entry_price) or not math.isfinite(pos.current_price):
            return False
        if not math.isfinite(pos.unrealized_pnl):
            return False
        if pos.duration_minutes is not None:
            try:
                if int(pos.duration_minutes) < 0:
                    return False
            except (TypeError, ValueError):
                return False

        if not self._is_valid_side(pos.side):
            return False

        normalized_symbol = self._normalize_symbol(pos.symbol)
        if not normalized_symbol:
            return False

        pos.symbol = normalized_symbol
        return True

    @staticmethod
    def _is_active_intent(record: Dict) -> bool:
        status = str(record.get("status", "")).strip().lower()
        if status not in {"pending", "submitted"}:
            return False

        created_at = RiskManager._to_float(record.get("created_at"), 0.0)
        if created_at <= 0:
            return False
        return (time.time() - created_at) < STATE_EXECUTION_INTENT_TTL_SECONDS

    def _cleanup_execution_intents(self):
        if not self.execution_intents:
            return

        now_ts = time.time()
        kept = {}
        for key, record in self.execution_intents.items():
            if not isinstance(record, dict):
                continue
            status = str(record.get("status", "")).strip().lower()
            created_at = self._to_float(record.get("created_at"), 0.0)
            if status == "completed":
                completed_age = now_ts - created_at
                if completed_age > STATE_EXECUTION_INTENT_COMPLETED_TTL_SECONDS:
                    continue
                kept[key] = record
                continue
            if created_at <= 0:
                continue
            if status in {"pending", "submitted", "failed"} and (now_ts - created_at) <= STATE_EXECUTION_INTENT_TTL_SECONDS:
                kept[key] = record

        if len(kept) != len(self.execution_intents):
            self.execution_intents = kept
            self._save_state()

    def _upsert_execution_intent(self, intent_key: str, updates: Dict) -> None:
        if not intent_key:
            return
        base = self.execution_intents.get(intent_key, {})
        if not isinstance(base, dict):
            base = {}
        now_ts = time.time()
        base.update(updates)
        base["updated_at"] = now_ts
        base.setdefault("created_at", now_ts)
        self.execution_intents[str(intent_key)] = base
        self._save_state()

    def reserve_execution_intent(
        self,
        market_id: str,
        side: str,
        size_usd: float,
        price: float,
        source: str = "",
        execution_mode: str = "",
    ) -> Tuple[bool, str, str]:
        self._cleanup_execution_intents()
        intent_key = self._build_execution_intent_key(
            market_id=market_id,
            side=side,
            size_usd=size_usd,
            price=price,
            source=source,
            execution_mode=execution_mode,
        )

        existing = self.execution_intents.get(intent_key, {})
        if self._is_active_intent(existing):
            return False, intent_key, f"execution intent already {existing.get('status')}"

        if str(existing.get("status", "")).strip().lower() == "completed":
            return False, intent_key, "execution already completed"

        self._upsert_execution_intent(
            intent_key,
            {
                "status": "pending",
                "market_id": str(market_id),
                "side": self._normalize_execution_side(side),
                "size_usd": _safe_float(size_usd, 0.0),
                "price": _safe_float(price, 0.0),
                "source": str(source or ""),
                "execution_mode": str(execution_mode or ""),
                "reason": "reserved",
            },
        )
        return True, intent_key, "reserved"

    def mark_execution_intent_submitted(
        self, intent_key: str, order_id: str = "", note: str = ""
    ) -> Optional[Dict]:
        existing = self.execution_intent(intent_key)
        if not existing:
            return None
        existing.update(
            {
                "status": "submitted",
                "order_id": str(order_id or existing.get("order_id", "")),
                "reason": str(note or existing.get("reason", "")),
            }
        )
        self._upsert_execution_intent(intent_key, existing)
        return existing

    def mark_execution_intent_completed(self, intent_key: str, note: str = "") -> Optional[Dict]:
        existing = self.execution_intent(intent_key)
        if not existing:
            return None
        existing.update({"status": "completed"})
        if note:
            existing["reason"] = str(note)
        self._upsert_execution_intent(intent_key, existing)
        return existing

    def mark_execution_intent_failed(self, intent_key: str, reason: str = "") -> Optional[Dict]:
        existing = self.execution_intent(intent_key)
        if not existing:
            return None
        existing.update({"status": "failed"})
        if reason:
            existing["reason"] = str(reason)
        self._upsert_execution_intent(intent_key, existing)
        return existing

    def execution_intent(self, intent_key: str) -> Optional[Dict]:
        record = self.execution_intents.get(intent_key, {})
        if not isinstance(record, dict):
            return None
        return dict(record)

    # ========================================================================
    # LIVE ORDER REGISTRY
    # ========================================================================

    @staticmethod
    def _normalize_live_order_status(status: str) -> str:
        normalized = str(status or "").strip().lower()
        if not normalized:
            return "submitted"
        return normalized

    def _is_live_order_active(self, record: Dict) -> bool:
        if not isinstance(record, dict):
            return False
        if str(record.get("final_disposition", "")).strip():
            return False
        status = self._normalize_live_order_status(record.get("status", ""))
        return status in {
            "submitted",
            "open_confirmed",
            "orphaned_pending_reconciliation",
            "timeout_cancel_failed",
            "open_after_cancel",
            "not_filled_external_queue",
            "not_filled_unknown",
            "not_filled",
        }

    def _has_orphaned_live_orders(self) -> bool:
        return any(
            (
                self._normalize_live_order_status(record.get("status", "")) == "orphaned_pending_reconciliation"
                or str(record.get("reconciliation_status", "")).strip().lower() == "orphaned_pending_reconciliation"
            )
            and not str(record.get("final_disposition", "")).strip()
            for record in self.live_orders.values()
            if isinstance(record, dict)
        )

    def _cleanup_live_orders(self) -> None:
        if not self.live_orders:
            return

        now_ts = time.time()
        kept: Dict[str, Dict] = {}
        for order_id, record in self.live_orders.items():
            if not isinstance(record, dict):
                continue

            created_at = self._to_float(record.get("created_at"), 0.0)
            updated_at = self._to_float(record.get("updated_at"), created_at)
            if created_at <= 0:
                created_at = now_ts
            if updated_at <= 0:
                updated_at = created_at

            final_disposition = str(record.get("final_disposition", "")).strip().lower()
            age = now_ts - updated_at
            if final_disposition and age > STATE_LIVE_ORDER_COMPLETED_TTL_SECONDS:
                continue
            kept[str(order_id)] = dict(record)

        if len(kept) != len(self.live_orders):
            self.live_orders = kept
            self._save_state()

    def _upsert_live_order(self, order_id: str, updates: Dict) -> Optional[Dict]:
        normalized_order_id = str(order_id or "").strip()
        if not normalized_order_id:
            return None

        now_ts = time.time()
        base = self.live_orders.get(normalized_order_id, {})
        if not isinstance(base, dict):
            base = {}
        base.update(updates)
        base["order_id"] = normalized_order_id
        base["status"] = self._normalize_live_order_status(base.get("status", "submitted"))
        base["updated_at"] = now_ts
        base.setdefault("created_at", now_ts)
        self.live_orders[normalized_order_id] = base
        self._save_state()
        return dict(base)

    def register_live_order(
        self,
        order_id: str,
        market_id: str,
        token_id: str,
        side: str,
        requested_size_usd: float,
        submitted_shares: float,
        submitted_notional_usd: float,
        decision_price: float,
        placed_price: float,
        execution_mode: str = "",
        prediction_path: str = "",
        intent_type: str = "entry",
    ) -> Optional[Dict]:
        return self._upsert_live_order(
            order_id,
            {
                "market_id": str(market_id or "").strip(),
                "token_id": self._normalize_token_id(token_id),
                "side": self._normalize_execution_side(side),
                "requested_size_usd": _safe_float(requested_size_usd, 0.0),
                "submitted_shares": _safe_float(submitted_shares, 0.0),
                "submitted_notional_usd": _safe_float(submitted_notional_usd, 0.0),
                "decision_price": _safe_float(decision_price, 0.0),
                "placed_price": _safe_float(placed_price, 0.0),
                "filled_shares": _safe_float(0.0, 0.0),
                "filled_notional_usd": _safe_float(0.0, 0.0),
                "execution_mode": str(execution_mode or ""),
                "prediction_path": str(prediction_path or ""),
                "intent_type": str(intent_type or "entry"),
                "status": "submitted",
                "reconciliation_status": "pending",
                "final_disposition": "",
                "fill_status_source": "",
                "status_reason": "",
            },
        )

    def update_live_order(self, order_id: str, **updates) -> Optional[Dict]:
        if "status" in updates:
            updates["status"] = self._normalize_live_order_status(updates.get("status"))
        if "reconciliation_status" in updates and updates.get("reconciliation_status") is not None:
            updates["reconciliation_status"] = str(updates.get("reconciliation_status"))
        if "final_disposition" in updates and updates.get("final_disposition") is not None:
            updates["final_disposition"] = str(updates.get("final_disposition"))
        return self._upsert_live_order(order_id, updates)

    def apply_live_order_result(self, order_id: str, fill_result: Optional[Dict]) -> Optional[Dict]:
        if not order_id:
            return None
        if not isinstance(fill_result, dict):
            return self.update_live_order(
                order_id,
                status="orphaned_pending_reconciliation",
                reconciliation_status="orphaned_pending_reconciliation",
                status_reason="missing fill result",
            )

        status = self._normalize_live_order_status(fill_result.get("status", "submitted"))
        fill_price = _safe_float(fill_result.get("fill_price"), 0.0)
        fill_shares = _safe_float(fill_result.get("fill_size"), 0.0)
        fill_notional = fill_shares * fill_price if fill_shares > 0 and fill_price > 0 else 0.0
        fill_source = str(fill_result.get("source", ""))

        final_disposition = ""
        reconciliation_status = status
        if status in {"filled", "filled_external"}:
            final_disposition = "filled"
            reconciliation_status = "trade_match" if status == "filled" else "external_trade_match"
        elif status in {"timeout_cancelled"}:
            final_disposition = "cancelled"
            reconciliation_status = "cancelled"
        elif status in {"timeout_cancel_failed", "open_after_cancel", "not_filled_external_queue", "not_filled_unknown", "not_filled"}:
            reconciliation_status = "orphaned_pending_reconciliation"

        updates = {
            "status": status,
            "reconciliation_status": reconciliation_status,
            "final_disposition": final_disposition,
            "filled_shares": fill_shares,
            "filled_notional_usd": fill_notional,
            "fill_status_source": fill_source,
            "status_reason": str(fill_result.get("reason", "")),
        }
        if final_disposition:
            updates["final_at"] = time.time()
        if fill_notional > 0:
            updates["placed_price"] = fill_price
        return self.update_live_order(order_id, **updates)

    def reconcile_live_orders(self, cli) -> List[Dict]:
        self._cleanup_live_orders()
        if not self.live_orders:
            return []

        try:
            open_orders = cli.get_open_orders()
        except Exception as exc:
            cprint(f"Failed to load open orders for reconciliation: {exc}", "yellow")
            open_orders = []

        try:
            trades = cli.get_trades()
        except Exception as exc:
            cprint(f"Failed to load trades for reconciliation: {exc}", "yellow")
            trades = []

        open_orders = open_orders if isinstance(open_orders, list) else []
        trades = trades if isinstance(trades, list) else []

        open_by_id = {}
        for order in open_orders:
            if not isinstance(order, dict):
                continue
            normalized_order = self._normalize_order_id(
                order.get("id", order.get("orderID", order.get("order_id", "")))
            )
            if normalized_order:
                open_by_id[normalized_order] = order

        trades_by_order = {}
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            normalized_order = self._normalize_order_id(
                trade.get("orderID", trade.get("order_id", trade.get("id", "")))
            )
            if normalized_order:
                trades_by_order[normalized_order] = trade

        now_ts = time.time()
        updates: List[Dict] = []
        for order_id, record in list(self.live_orders.items()):
            if not isinstance(record, dict) or not self._is_live_order_active(record):
                continue

            normalized_order_id = self._normalize_order_id(order_id)
            existing_status = self._normalize_live_order_status(record.get("status", "submitted"))
            matched_open = open_by_id.get(normalized_order_id)
            if matched_open is not None:
                changed = self.update_live_order(
                    order_id,
                    status="open_confirmed",
                    reconciliation_status="open_confirmed",
                    last_seen_open_at=now_ts,
                    placed_price=_safe_float(
                        matched_open.get("price", record.get("placed_price", 0.0)),
                        _safe_float(record.get("placed_price", 0.0), 0.0),
                    ),
                    submitted_shares=_safe_float(
                        matched_open.get("size", matched_open.get("original_size", record.get("submitted_shares", 0.0))),
                        _safe_float(record.get("submitted_shares", 0.0), 0.0),
                    ),
                    status_reason="open order still present on book",
                )
                if changed and existing_status != "open_confirmed":
                    updates.append(
                        {
                            "order_id": order_id,
                            "status_before": existing_status,
                            "status_after": "open_confirmed",
                        }
                    )
                continue

            matched_trade = trades_by_order.get(normalized_order_id)
            if matched_trade is not None:
                fill_price = _safe_float(matched_trade.get("price", 0.0), 0.0)
                fill_shares = _safe_float(
                    matched_trade.get("size", matched_trade.get("amount", 0.0)), 0.0
                )
                self.update_live_order(
                    order_id,
                    status="filled",
                    reconciliation_status="trade_match",
                    final_disposition="filled",
                    filled_shares=fill_shares,
                    filled_notional_usd=fill_shares * fill_price,
                    fill_status_source="reconciliation_order_match",
                    final_at=now_ts,
                    status_reason="trade matched by order id",
                )
                if existing_status != "filled":
                    updates.append(
                        {
                            "order_id": order_id,
                            "status_before": existing_status,
                            "status_after": "filled",
                        }
                    )
                continue

            market_id = str(record.get("market_id", "")).strip()
            token_id = self._normalize_token_id(record.get("token_id", ""))
            submitted_shares = _safe_float(record.get("submitted_shares", 0.0), 0.0)
            fallback_trade = None
            for trade in trades:
                if not isinstance(trade, dict):
                    continue
                trade_market = self._normalize_token_id(
                    trade.get("market_id", trade.get("market", trade.get("condition_id", "")))
                )
                trade_token = self._normalize_token_id(trade.get("token_id", trade.get("tokenId", "")))
                if market_id and trade_market and self._normalize_token_id(market_id) != trade_market:
                    continue
                if token_id and trade_token and token_id != trade_token:
                    continue
                observed_size = _safe_float(trade.get("size", trade.get("amount", 0.0)), 0.0)
                if submitted_shares > 0 and observed_size > 0:
                    ratio = observed_size / submitted_shares
                    if ratio < 0.25 or ratio > 2.5:
                        continue
                fallback_trade = trade
                break

            if fallback_trade is not None:
                fill_price = _safe_float(fallback_trade.get("price", 0.0), 0.0)
                fill_shares = _safe_float(
                    fallback_trade.get("size", fallback_trade.get("amount", 0.0)), 0.0
                )
                self.update_live_order(
                    order_id,
                    status="filled_external",
                    reconciliation_status="external_trade_match",
                    final_disposition="filled",
                    filled_shares=fill_shares,
                    filled_notional_usd=fill_shares * fill_price,
                    fill_status_source="reconciliation_external_match",
                    final_at=now_ts,
                    status_reason="trade matched by token/market correlation",
                )
                if existing_status != "filled_external":
                    updates.append(
                        {
                            "order_id": order_id,
                            "status_before": existing_status,
                            "status_after": "filled_external",
                        }
                    )
                continue

            if existing_status != "orphaned_pending_reconciliation":
                self.update_live_order(
                    order_id,
                    status="orphaned_pending_reconciliation",
                    reconciliation_status="orphaned_pending_reconciliation",
                    status_reason="order missing from open orders and trades",
                )
                updates.append(
                    {
                        "order_id": order_id,
                        "status_before": existing_status,
                        "status_after": "orphaned_pending_reconciliation",
                    }
                )

        return updates

    # ========================================================================
    # POSITION TRACKING
    # ========================================================================

    def add_position(
        self,
        execution: TradeExecution,
        question: str = "",
        end_date=None,
        duration_minutes=None,
        source: str = "",
        symbol: str = "",
    ) -> Position:
        """
        Track a new position from a trade execution.
        """
        market_id = str(execution.market_id or "").strip()
        if not market_id:
            raise ValueError("market id is required for position tracking")

        normalized_symbol = self._normalize_symbol(symbol)
        normalized_token_id = self._normalize_token_id(execution.token_id)
        if not normalized_token_id:
            raise ValueError(f"invalid token id for market {market_id}")

        normalized_side = self._normalize_execution_side(execution.side)
        if not self._is_valid_side(normalized_side):
            raise ValueError(f"invalid position side for market {market_id}: {execution.side}")

        size_usd = _safe_float(
            execution.filled_notional_usd or execution.submitted_notional_usd or execution.size_usd,
            -1.0,
        )
        entry_price = _safe_float(execution.price, -1.0)
        if size_usd <= 0 or entry_price <= 0:
            raise ValueError(f"invalid size or price for market {market_id}: {size_usd} @ {entry_price}")

        shares_count = _safe_float(
            execution.filled_shares or execution.submitted_shares or (size_usd / entry_price if entry_price > 0 else 0.0),
            0.0,
        )

        pos = Position(
            market_id=market_id,
            token_id=normalized_token_id,
            side=normalized_side,
            size_usd=size_usd,
            entry_price=entry_price,
            current_price=entry_price,
            entry_time=execution.timestamp,
            question=question,
            end_date=end_date,
            duration_minutes=duration_minutes,
            source=source,
            symbol=normalized_symbol,
            requested_size_usd=_safe_float(execution.requested_size_usd or execution.size_usd, size_usd),
            shares_count=shares_count,
            filled_notional_usd=_safe_float(execution.filled_notional_usd or size_usd, size_usd),
            entry_order_id=str(execution.order_id or ""),
        )

        if market_id in self.positions:
            raise ValueError(
                f"duplicate market id when adding position: {market_id}"
            )
        if any(
            existing.token_id == pos.token_id
            for existing in self.positions.values()
            if existing.market_id != market_id
        ):
            raise ValueError(f"token id already tracked for another market: {pos.token_id}")

        if not self._invariant_position(pos):
            raise ValueError(f"invalid position payload for market {market_id}")

        self._unresolved_closed_markets.pop(market_id, None)
        self.positions[pos.market_id] = pos
        self._save_state()
        return pos

    def update_position_price(self, market_id: str, current_price: float):
        """
        Update mark-to-market price for a position.
        """
        if market_id in self.positions:
            self.positions[market_id].update_price(_safe_float(current_price, self.positions[market_id].current_price))

    def close_position(self, market_id: str, close_price: float) -> float:
        """
        Close a position and return realized P&L.
        """
        if market_id not in self.positions:
            return 0.0

        pos = self.positions[market_id]
        close_price = _safe_float(close_price, pos.current_price)
        pos.update_price(close_price)
        pnl = _safe_float(pos.unrealized_pnl, 0.0)
        if not math.isfinite(pnl):
            pnl = 0.0

        bucket = self._expiry_bucket(pos.duration_minutes)
        bucket_stats = self._expiry_stats.setdefault(bucket, {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0})
        bucket_stats["trades"] += 1
        bucket_stats["total_pnl"] += pnl
        if pnl >= 0:
            bucket_stats["wins"] += 1
        else:
            bucket_stats["losses"] += 1

        sym = self._normalize_symbol(pos.symbol or "OTHER")
        sym_stats = self._symbol_stats.setdefault(sym, {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0})
        sym_stats["trades"] += 1
        sym_stats["total_pnl"] += pnl
        if pnl >= 0:
            sym_stats["wins"] += 1
        else:
            sym_stats["losses"] += 1

        src = self._normalize_symbol(pos.source or "unknown")
        src_stats = self._source_stats.setdefault(src, {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0})
        src_stats["trades"] += 1
        src_stats["total_pnl"] += pnl
        if pnl >= 0:
            src_stats["wins"] += 1
        else:
            src_stats["losses"] += 1

        self.daily_pnl += pnl
        if not math.isfinite(self.daily_pnl):
            self.daily_pnl = 0.0
        self._unresolved_closed_markets.pop(market_id, None)
        del self.positions[market_id]
        self._save_state()

        return pnl

    @staticmethod
    def _expiry_bucket(duration_minutes: Optional[int]) -> str:
        if duration_minutes is None:
            return "unknown"
        if duration_minutes <= 5:
            return "5min"
        if duration_minutes <= 15:
            return "15min"
        if duration_minutes <= 30:
            return "30min"
        if duration_minutes <= 60:
            return "1hour"
        if duration_minutes <= 240:
            return "4hour"
        if duration_minutes <= 1440:
            return "same_day"
        return "multi_day"

    def print_expiry_stats(self):
        """
        Print performance breakdown by expiry bucket.
        """
        if not self._expiry_stats:
            return
        cprint("\n  Performance by Expiry Bucket:", "cyan")
        cprint(f"  {'Bucket':<12} {'Trades':>6} {'Wins':>5} {'Losses':>6} {'Win%':>6} {'PnL':>10}", "white")
        cprint(f"  {'-'*50}", "white")
        for bucket in ["5min", "15min", "30min", "1hour", "4hour", "same_day", "multi_day", "unknown"]:
            stats = self._expiry_stats.get(bucket)
            if not stats or stats["trades"] == 0:
                continue
            win_pct = (stats["wins"] / stats["trades"]) * 100
            color = "green" if stats["total_pnl"] >= 0 else "red"
            cprint(
                f"  {bucket:<12} {stats['trades']:>6} {stats['wins']:>5} "
                f"{stats['losses']:>6} {win_pct:>5.1f}% ${stats['total_pnl']:>+9.2f}",
                color,
            )

    def print_edge_summary(self):
        """
        Print edge/position quality summary.
        """
        has_data = self._symbol_stats or self._source_stats or self._expiry_stats
        if not has_data:
            return

        cprint("\n  Edge Summary:", "cyan")

        if self._symbol_stats:
            parts = []
            for sym in sorted(self._symbol_stats.keys()):
                s = self._symbol_stats[sym]
                if s["trades"] == 0:
                    continue
                win_pct = (s["wins"] / s["trades"]) * 100
                parts.append(f"{sym}: {s['trades']} trades, {win_pct:.0f}% win, ${s['total_pnl']:+.2f}")
            if parts:
                cprint(f"    By Symbol:    {' | '.join(parts)}", "white")

        if self._source_stats:
            parts = []
            for src in sorted(self._source_stats.keys()):
                s = self._source_stats[src]
                if s["trades"] == 0:
                    continue
                win_pct = (s["wins"] / s["trades"]) * 100
                label = src.capitalize() if src != "arbitrage" else "Arb"
                parts.append(f"{label}: {s['trades']} trades, {win_pct:.0f}% win, ${s['total_pnl']:+.2f}")
            if parts:
                cprint(f"    By Source:    {' | '.join(parts)}", "white")

        if self._expiry_stats:
            parts = []
            for bucket in ["5min", "15min", "30min", "1hour", "4hour", "same_day", "multi_day", "unknown"]:
                s = self._expiry_stats.get(bucket)
                if not s or s["trades"] == 0:
                    continue
                win_pct = (s["wins"] / s["trades"]) * 100
                parts.append(f"{bucket}: {s['trades']} trades, {win_pct:.0f}% win, ${s['total_pnl']:+.2f}")
            if parts:
                cprint(f"    By Timeframe: {' | '.join(parts)}", "white")

    # ------------------------------------------------------------------ position management

    def refresh_position_prices(self, cli) -> Dict[str, float]:
        """
        Refresh current prices for all open positions via CLOB.
        Returns dict of {market_id: new_price} for positions that updated.
        """
        updated = {}
        for market_id, pos in list(self.positions.items()):
            market_data = cli.get_clob_market(market_id)
            if not market_data:
                continue

            tokens = market_data.get("tokens", [])
            new_price: Optional[float] = None
            for token in tokens:
                if not isinstance(token, dict):
                    continue
                token_id = self._normalize_token_id(token.get("token_id", token.get("tokenId", "")))
                if not token_id:
                    continue
                if token_id == self._normalize_token_id(pos.token_id):
                    new_price = _safe_float(token.get("price"), pos.current_price)
                    break

            if new_price is None:
                continue

            pos.update_price(new_price)
            updated[market_id] = new_price

        if updated:
            self._save_state()
        return updated

    def check_resolved_markets(self, cli) -> List[Dict]:
        """
        Check all positions for market resolution.
        Returns list of resolved market summaries.
        """
        resolved = []
        now_ts = time.time()
        unresolved_changes = False

        def _record_stale_resolution(
            market_id: str,
            pos,
            marker_age: float,
            reason: str,
            source: str,
        ) -> None:
            if marker_age < STATE_RESOLVED_STALE_SECONDS:
                return
            fallback_close_price = _safe_float(pos.current_price, pos.entry_price)
            try:
                pnl = self.close_position(market_id, fallback_close_price)
            except Exception as exc:
                resolved.append(
                    {
                        "market_id": market_id,
                        "question": pos.question,
                        "side": pos.side,
                        "outcome": "",
                        "our_side_won": False,
                        "pnl": 0.0,
                        "size_usd": pos.size_usd,
                        "entry_price": pos.entry_price,
                        "resolution_note": reason,
                        "resolution_source": source,
                        "resolution_error": str(exc),
                    }
                )
                return

            resolved.append(
                {
                    "market_id": market_id,
                    "question": pos.question,
                    "side": pos.side,
                    "outcome": "",
                    "our_side_won": False,
                    "pnl": pnl,
                    "size_usd": pos.size_usd,
                    "entry_price": pos.entry_price,
                    "resolution_note": reason,
                    "resolution_source": source,
                }
            )

        for market_id, pos in list(self.positions.items()):
            market_data = cli.get_clob_market(market_id)
            if not isinstance(market_data, dict) or not market_data:
                marker = self._mark_unresolved_closed_market(market_id, now_ts)
                unresolved_changes = True
                marker_age = now_ts - marker
                _record_stale_resolution(
                    market_id=market_id,
                    pos=pos,
                    marker_age=marker_age,
                    reason="stale_no_data",
                    source="stale_recovery",
                )
                continue

            closed = bool(market_data.get("closed", market_data.get("isClosed", False)))
            active = bool(market_data.get("active", True))
            outcome, outcome_source = self._infer_resolved_outcome(market_data)

            if not outcome:
                market_is_settling = (not active) or closed
                if not market_is_settling:
                    if market_id in self._unresolved_closed_markets:
                        self._unresolved_closed_markets.pop(market_id, None)
                        unresolved_changes = True
                    continue

                marker = self._mark_unresolved_closed_market(market_id, now_ts)
                unresolved_changes = True
                marker_age = now_ts - marker
                _record_stale_resolution(
                    market_id=market_id,
                    pos=pos,
                    marker_age=marker_age,
                    reason="stale_no_winner",
                    source="stale_recovery",
                )
                continue

            self._unresolved_closed_markets.pop(market_id, None)
            unresolved_changes = True

            pos_outcome = (pos.side == "YES" and outcome == "YES") or (
                pos.side == "NO" and outcome == "NO"
            )
            close_price = 1.0 if pos_outcome else 0.0
            pnl = self.close_position(market_id, close_price)
            resolved.append(
                {
                    "market_id": market_id,
                    "question": pos.question,
                    "side": pos.side,
                    "outcome": outcome,
                    "our_side_won": pos_outcome,
                    "pnl": pnl,
                    "size_usd": pos.size_usd,
                    "entry_price": pos.entry_price,
                    "resolution_source": outcome_source,
                }
            )

        if unresolved_changes and not resolved:
            self._save_state()

        return resolved

    def check_exit_signals(self) -> List[str]:
        """
        Check positions for exit signals.
        For short-expiry markets, add time-based exit rules with tighter thresholds.
        """
        exits = []
        for market_id, pos in self.positions.items():
            if pos.is_resolved:
                continue

            hours_left = pos.time_remaining_hours
            is_short_expiry = pos.duration_minutes is not None and pos.duration_minutes <= 60

            if is_short_expiry and hours_left < (1.0 / 60.0):
                exits.append(market_id)
                continue

            if is_short_expiry and pos.size_usd > 0 and pos.duration_minutes:
                duration_hours = max(1.0, (pos.duration_minutes or 60) / 60.0)
                fraction_elapsed = max(0.0, min(1.0, 1.0 - (hours_left / duration_hours)))

                if fraction_elapsed > 0.75:
                    if pos.return_pct < -15.0 or pos.return_pct > 20.0:
                        exits.append(market_id)
                        continue
                elif fraction_elapsed > 0.50:
                    if pos.return_pct < -20.0 or pos.return_pct > 35.0:
                        exits.append(market_id)
                        continue

            if pos.return_pct < -30.0 or pos.return_pct > 50.0:
                exits.append(market_id)

        return exits

    # ------------------------------------------------------------------ pre-trade checks

    def can_trade(
        self,
        market_id: str,
        size_usd: float,
        symbol: str = "",
        side: str = "",
        end_date: Optional[datetime] = None,
        source: str = "",
        price: Optional[float] = None,
        execution_intent_key: str = "",
    ) -> Tuple[bool, str]:
        """
        Run all risk checks before allowing a trade.
        Returns (allowed, reason).
        """
        self._check_daily_reset()

        market_id = str(market_id or "").strip()
        if not market_id:
            return False, "RISK_REJECT_BAD_MARKET_ID: market_id missing"

        if self._halted:
            return False, f"RISK_HALT: {self._halt_reason}"

        if self._has_orphaned_live_orders():
            return False, "RISK_REJECT_ORPHANED_LIVE_ORDER: reconcile unresolved live orders first"

        size = _safe_float(size_usd, float("nan"))
        if not math.isfinite(size):
            return False, "RISK_REJECT_BAD_SIZE: size not finite"
        if size <= 0:
            return False, "RISK_REJECT_BAD_SIZE: size must be positive"

        if price is not None:
            decision_price = _safe_float(price, float("nan"))
            if not math.isfinite(decision_price):
                return False, "RISK_REJECT_BAD_PRICE: price not finite"
            if decision_price <= 0 or decision_price >= 1:
                return False, f"RISK_REJECT_BAD_PRICE: price out of range ({decision_price:.4f})"

        normalized_symbol = self._normalize_symbol(symbol)
        if side:
            normalized_side = self._normalize_execution_side(side)
            if not self._is_valid_side(normalized_side):
                return False, f"RISK_REJECT_INVALID_SIDE: {side}"
            side = normalized_side

        max_daily = max(1, int(getattr(self.config, "max_daily_trades", 1)))
        if self.daily_trade_count >= max_daily:
            return False, f"RISK_REJECT_DAILY_COUNT: {self.daily_trade_count}/{max_daily}"

        per_market_cap = _safe_float(getattr(self.config, "max_per_market_usd", 0.0), 0.0)
        if per_market_cap > 0 and size > per_market_cap:
            return False, f"RISK_REJECT_PER_MARKET_CAP: {size:.2f} > {per_market_cap:.2f}"

        if end_date is not None and end_date <= datetime.utcnow():
            return False, "RISK_REJECT_EXPIRED_MARKET: market already expired"

        if self.daily_pnl < -_safe_float(self.config.daily_loss_limit_usd, 0.0):
            self.halt_trading("Daily loss limit reached", "DAILY_LOSS")
            return False, f"RISK_REJECT: {self._halt_reason}"

        if market_id in self.positions:
            return False, f"RISK_REJECT_DUPLICATE_MARKET: {market_id}"

        if any(
            str(record.get("market_id", "")).strip() == market_id and self._is_live_order_active(record)
            for record in self.live_orders.values()
        ):
            return False, f"RISK_REJECT_PENDING_LIVE_ORDER: {market_id}"

        if not execution_intent_key and side and symbol and size_usd >= 0:
            execution_intent_key = self._build_execution_intent_key(
                market_id=market_id,
                side=side,
                size_usd=size_usd,
                price=price or 0.0,
                source=source,
                execution_mode="",
            )

        if execution_intent_key:
            rec = self.execution_intent(execution_intent_key)
            if rec is not None and self._is_active_intent(rec):
                return (
                    False,
                    f"RISK_REJECT_PENDING_EXECUTION: {rec.get('status', 'unknown')}",
                )

        if len(self.positions) >= int(self.config.max_positions):
            return False, f"RISK_REJECT_POSITION_LIMIT: {len(self.positions)}/{self.config.max_positions}"

        normalized_symbol = self._normalize_symbol(symbol)

        if normalized_symbol and normalized_symbol != "OTHER":
            symbol_count = sum(1 for p in self.positions.values() if p.symbol == normalized_symbol)
            if symbol_count >= int(self.config.max_positions_per_symbol):
                return (
                    False,
                    f"RISK_REJECT_SYMBOL_LIMIT: {normalized_symbol} {symbol_count}/{self.config.max_positions_per_symbol}",
                )

        if side and normalized_symbol and normalized_symbol != "OTHER" and end_date is not None:
            side = str(side).upper()
            for pos in self.positions.values():
                if (
                    pos.symbol == normalized_symbol
                    and pos.side != side
                    and pos.end_date
                    and pos.end_date.date() == end_date.date()
                ):
                    return (
                        False,
                        f"RISK_REJECT_CORRELATION: existing opposing side on {normalized_symbol} for {end_date.date()}",
                    )

        if side and normalized_symbol and normalized_symbol != "OTHER":
            max_same_dir = int(getattr(self.config, "max_positions_per_direction", 3))
            same_direction = sum(
                1 for p in self.positions.values()
                if p.symbol == normalized_symbol and p.side == side
            )
            if same_direction >= max_same_dir:
                return (
                    False,
                    f"RISK_REJECT_DIRECTION_LIMIT: {normalized_symbol} {side} {same_direction}/{max_same_dir}",
                )

        source_cap = _safe_float(getattr(self.config, "max_total_exposure_usd", 0.0), 0.0)
        pending_live = self.pending_live_notional
        if self.total_exposure + pending_live + size > source_cap:
            return (
                False,
                f"RISK_REJECT_EXPOSURE: {self.total_exposure:.2f}+{pending_live:.2f}+{size:.2f} > {source_cap:.2f}",
            )

        if source in {"arbitrage", "swarm"} and size < _safe_float(self.config.min_position_usd, 0.0):
            return (
                False,
                f"RISK_REJECT_MIN_SIZE: size {size:.2f} < min {self.config.min_position_usd:.2f}",
            )

        return True, "OK"

    # ------------------------------------------------------------------ circuit breakers

    def check_circuit_breakers(self):
        """
        Called each cycle. Check all circuit breaker conditions.
        """
        self._check_daily_reset()
        if self.daily_pnl < -_safe_float(self.config.daily_loss_limit_usd, 0.0):
            self.halt_trading(
                f"Daily loss limit reached: ${self.daily_pnl:.2f}",
                "DAILY_LOSS_LIMIT",
            )
            return

        unrealized_limit = _safe_float(getattr(self.config, "unrealized_loss_limit_usd", 0.0), 0.0)
        if unrealized_limit > 0 and self.total_unrealized_pnl < -unrealized_limit:
            self.halt_trading(
                f"Unrealized loss limit reached: ${self.total_unrealized_pnl:.2f}",
                "UNREALIZED_LOSS_LIMIT",
            )
            return

        stale_threshold = max(30, int(getattr(self.config, "live_order_stale_seconds", 300)))
        now_ts = time.time()
        for record in self.live_orders.values():
            if not self._is_live_order_active(record):
                continue
            created_at = self._to_float(record.get("created_at"), 0.0)
            if created_at <= 0:
                continue
            age = now_ts - created_at
            if age >= stale_threshold:
                self.halt_trading(
                    f"Stale live order detected after {age:.0f}s: {record.get('order_id', '')}",
                    "STALE_LIVE_ORDER",
                )
                return

    def halt_trading(self, reason: str, reason_code: str = "MANUAL"):
        """
        Emergency halt.
        """
        self._halted = True
        self._halt_reason = reason
        self._halt_reason_code = reason_code
        cprint(f"TRADING HALTED ({reason_code}): {reason}", "red")
        self._save_state()

    def resume_trading(self, reason_code: str = "RESUME"):
        """
        Resume after halt.
        """
        self._halted = False
        self._halt_reason = ""
        self._halt_reason_code = reason_code
        cprint("Trading resumed", "green")
        self._save_state()

    # ------------------------------------------------------------------ daily reset

    def _check_daily_reset(self):
        """
        Reset daily counters if new day.
        """
        today = date.today().isoformat()
        reset_happened = False
        if today != self._today:
            cprint("New day — resetting daily counters", "cyan")
            self.daily_pnl = 0.0
            self.daily_trade_count = 0
            self._today = today
            reset_happened = True
        if self._halted and self._halt_reason_code in {"DAILY_LOSS_LIMIT", "DAILY_LOSS"}:
            self.resume_trading("DAILY_RESET")
            return
        if reset_happened:
            self._save_state()

    # ------------------------------------------------------------------ persistence

    def _load_state(self):
        """
        Load positions and state from disk with schema-aware migration.
        """
        state_file = self.config.positions_dir / "risk_state.json"
        if not state_file.exists():
            return

        try:
            with open(state_file) as f:
                data = json.load(f)

            if not isinstance(data, dict):
                cprint("Risk state file malformed: top-level JSON is not an object", "yellow")
                return

            schema = _safe_int(data.get("_schema_version", 1), 1)
            if schema > self._state_schema_version:
                cprint(
                    f"Risk state schema {schema} newer than runtime {self._state_schema_version}",
                    "yellow",
                )

            self.daily_pnl = _safe_float(data.get("daily_pnl", 0.0), 0.0)
            self.daily_trade_count = _safe_int(data.get("daily_trade_count", 0), 0)
            self._halted = bool(data.get("halted", False))
            self._halt_reason = str(data.get("halt_reason", ""))
            self._halt_reason_code = str(data.get("halt_reason_code", ""))
            self._today = str(data.get("today", date.today().isoformat()))
            self._expiry_stats = data.get("expiry_stats", {}) if isinstance(data.get("expiry_stats", {}), dict) else {}
            self._symbol_stats = data.get("symbol_stats", {}) if isinstance(data.get("symbol_stats", {}), dict) else {}
            self._source_stats = data.get("source_stats", {}) if isinstance(data.get("source_stats", {}), dict) else {}

            self.execution_intents = {}
            intent_payload = data.get("execution_intents", {}) or {}
            if isinstance(intent_payload, dict):
                for key, payload in intent_payload.items():
                    if not isinstance(key, str) or not key.strip():
                        continue
                    if not isinstance(payload, dict):
                        continue
                    status = str(payload.get("status", "failed")).strip().lower()
                    if status not in {"pending", "submitted", "completed", "failed"}:
                        status = "failed"
                    created_at = self._safe_positive_float(payload.get("created_at"), 0.0)
                    updated_at = self._safe_positive_float(payload.get("updated_at"), created_at)
                    if created_at is None:
                        created_at = 0.0
                    if updated_at is None:
                        updated_at = created_at

                    self.execution_intents[str(key)] = {
                        "status": status,
                        "market_id": str(payload.get("market_id", "")),
                        "side": self._normalize_execution_side(payload.get("side", "")),
                        "size_usd": _safe_float(payload.get("size_usd"), 0.0),
                        "price": _safe_float(payload.get("price"), 0.0),
                        "source": str(payload.get("source", "")),
                        "execution_mode": str(payload.get("execution_mode", "")),
                        "created_at": created_at,
                        "updated_at": updated_at if updated_at >= created_at else created_at,
                        "order_id": str(payload.get("order_id", "")) if payload.get("order_id") else "",
                        "reason": str(payload.get("reason", "")),
                        "error": str(payload.get("error", "")),
                    }

            self.live_orders = {}
            live_order_payload = data.get("live_orders", {}) or {}
            if isinstance(live_order_payload, dict):
                for key, payload in live_order_payload.items():
                    if not isinstance(payload, dict):
                        continue
                    normalized_order_id = self._normalize_order_id(key)
                    if not normalized_order_id:
                        normalized_order_id = self._normalize_order_id(payload.get("order_id", ""))
                    if not normalized_order_id:
                        continue

                    created_at = self._safe_positive_float(payload.get("created_at"), 0.0)
                    updated_at = self._safe_positive_float(payload.get("updated_at"), created_at)
                    if created_at is None:
                        created_at = 0.0
                    if updated_at is None:
                        updated_at = created_at

                    self.live_orders[normalized_order_id] = {
                        "order_id": normalized_order_id,
                        "market_id": str(payload.get("market_id", "")).strip(),
                        "token_id": self._normalize_token_id(payload.get("token_id", "")),
                        "side": self._normalize_execution_side(payload.get("side", "")),
                        "requested_size_usd": _safe_float(payload.get("requested_size_usd"), 0.0),
                        "submitted_shares": _safe_float(payload.get("submitted_shares"), 0.0),
                        "submitted_notional_usd": _safe_float(payload.get("submitted_notional_usd"), 0.0),
                        "filled_shares": _safe_float(payload.get("filled_shares"), 0.0),
                        "filled_notional_usd": _safe_float(payload.get("filled_notional_usd"), 0.0),
                        "decision_price": _safe_float(payload.get("decision_price"), 0.0),
                        "placed_price": _safe_float(payload.get("placed_price"), 0.0),
                        "status": self._normalize_live_order_status(payload.get("status", "submitted")),
                        "reconciliation_status": str(payload.get("reconciliation_status", "pending")),
                        "final_disposition": str(payload.get("final_disposition", "")),
                        "status_reason": str(payload.get("status_reason", "")),
                        "fill_status_source": str(payload.get("fill_status_source", "")),
                        "execution_mode": str(payload.get("execution_mode", "")),
                        "prediction_path": str(payload.get("prediction_path", "")),
                        "intent_type": str(payload.get("intent_type", "entry")),
                        "created_at": created_at,
                        "updated_at": updated_at if updated_at >= created_at else created_at,
                        "last_seen_open_at": self._safe_positive_float(payload.get("last_seen_open_at"), None),
                        "final_at": self._safe_positive_float(payload.get("final_at"), None),
                    }

            unresolved = data.get("unresolved_closed_markets", {}) or {}
            if isinstance(unresolved, dict):
                parsed_unresolved: Dict[str, float] = {}
                for market_id, marker in unresolved.items():
                    if not isinstance(market_id, str) or not market_id.strip():
                        continue
                    safe_marker = self._safe_positive_float(marker, None)
                    if safe_marker is None:
                        continue
                    parsed_unresolved[market_id.strip()] = safe_marker
                self._unresolved_closed_markets = parsed_unresolved
            else:
                self._unresolved_closed_markets = {}

            resolved_positions: Dict[str, Position] = {}
            for pos_data in data.get("positions", []):
                if not isinstance(pos_data, dict):
                    self._invalid_state_rows += 1
                    continue

                market_id = str(pos_data.get("market_id", "")).strip()
                if not market_id:
                    self._invalid_state_rows += 1
                    continue

                incoming_entry = self._to_datetime(pos_data.get("entry_time"))
                if incoming_entry is None:
                    incoming_entry = datetime.utcnow()
                existing = resolved_positions.get(market_id)
                if existing is not None and existing.entry_time >= incoming_entry:
                    self._invalid_state_rows += 1
                    continue

                token_id = self._normalize_token_id(pos_data.get("token_id", ""))
                side = str(pos_data.get("side", "")).upper()
                size_usd = _safe_float(pos_data.get("size_usd", 0.0), 0.0)
                entry_price = _safe_float(pos_data.get("entry_price", 0.0), 0.0)
                current_price = _safe_float(pos_data.get("current_price", 0.0), entry_price)
                unrealized_pnl = _safe_float(pos_data.get("unrealized_pnl", 0.0), 0.0)

                if not token_id or not self._is_valid_side(side):
                    self._invalid_state_rows += 1
                    continue
                if size_usd <= 0.0 or entry_price < 0.0 or current_price < 0.0 or not math.isfinite(size_usd):
                    self._invalid_state_rows += 1
                    continue

                pos = Position(
                    market_id=market_id,
                    token_id=token_id,
                    side=side,
                    size_usd=size_usd,
                    entry_price=entry_price,
                    current_price=current_price,
                    entry_time=incoming_entry,
                    question=str(pos_data.get("question", "")),
                    unrealized_pnl=unrealized_pnl,
                    is_resolved=bool(pos_data.get("is_resolved", False)),
                    resolved_outcome=str(pos_data.get("resolved_outcome", "")),
                    end_date=self._to_datetime(pos_data.get("end_date")),
                    duration_minutes=_safe_int(pos_data.get("duration_minutes"), None),
                    source=str(pos_data.get("source", "")),
                    symbol=self._normalize_symbol(pos_data.get("symbol", "")),
                    requested_size_usd=_safe_float(pos_data.get("requested_size_usd", size_usd), size_usd),
                    shares_count=_safe_float(pos_data.get("shares", pos_data.get("shares_count", 0.0)), 0.0),
                    filled_notional_usd=_safe_float(pos_data.get("filled_notional_usd", size_usd), size_usd),
                    entry_order_id=str(pos_data.get("entry_order_id", "")),
                )
                if not self._invariant_position(pos):
                    self._invalid_state_rows += 1
                    continue

                if any(
                    existing.token_id == token_id and existing.market_id != market_id
                    for existing in resolved_positions.values()
                ):
                    self._invalid_state_rows += 1
                    continue

                resolved_positions[market_id] = pos

            self.positions = resolved_positions

            if self._invalid_state_rows:
                cprint(
                    f"Risk state loaded with {self._invalid_state_rows} invalid rows skipped",
                    "yellow",
                )

            self._migrate_state(schema)
            self._cleanup_execution_intents()
            self._cleanup_live_orders()
        except Exception as e:
            cprint(f"Failed to load risk state: {e}", "yellow")

    def _migrate_state(self, old_schema: int):
        """
        Keep schema-compatible state migration hooks.
        """
        if old_schema < 2:
            # Schema v2 introduces explicit schema field and unresolved marker.
            for pos in self.positions.values():
                pos.symbol = self._normalize_symbol(pos.symbol)
            if self._state_schema_version >= 2:
                self._save_state()
        if old_schema < 3 and self._state_schema_version >= 3:
            if self.execution_intents:
                self._save_state()
        if old_schema < 4 and self._state_schema_version >= 4:
            for market_id, marker in list(self._unresolved_closed_markets.items()):
                safe_marker = self._safe_positive_float(marker, None)
                if safe_marker is None:
                    self._unresolved_closed_markets.pop(market_id, None)
            if self._unresolved_closed_markets:
                self._save_state()
        if old_schema < 5 and self._state_schema_version >= 5:
            self._save_state()

    def _save_state(self):
        """
        Persist current state to disk atomically.
        """
        self.config.ensure_dirs()
        state_file = self.config.positions_dir / "risk_state.json"

        data = {
            "_schema_version": self._state_schema_version,
            "daily_pnl": _safe_float(self.daily_pnl, 0.0),
            "daily_trade_count": int(self.daily_trade_count),
            "halted": bool(self._halted),
            "halt_reason": str(self._halt_reason),
            "halt_reason_code": str(self._halt_reason_code),
            "today": str(self._today),
            "positions": [p.to_dict() for p in self.positions.values()],
            "execution_intents": self.execution_intents,
            "live_orders": self.live_orders,
            "expiry_stats": self._expiry_stats,
            "symbol_stats": self._symbol_stats,
            "source_stats": self._source_stats,
            "unresolved_closed_markets": self._unresolved_closed_markets,
        }

        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self.config.positions_dir), suffix=".tmp"
            )
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(state_file))
        except Exception as e:
            cprint(f"Failed to save risk state: {e}", "red")
            try:
                if tmp_path is not None and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass

    # ------------------------------------------------------------------ reporting

    @property
    def total_exposure(self) -> float:
        return sum(_safe_float(p.size_usd, 0.0) for p in self.positions.values())

    @property
    def total_unrealized_pnl(self) -> float:
        return sum(_safe_float(p.unrealized_pnl, 0.0) for p in self.positions.values())

    @property
    def pending_live_notional(self) -> float:
        return sum(
            _safe_float(record.get("submitted_notional_usd", record.get("requested_size_usd", 0.0)), 0.0)
            for record in self.live_orders.values()
            if self._is_live_order_active(record)
        )

    @property
    def stale_live_order_count(self) -> int:
        threshold = max(30, int(getattr(self.config, "live_order_stale_seconds", 300)))
        now_ts = time.time()
        count = 0
        for record in self.live_orders.values():
            if not self._is_live_order_active(record):
                continue
            created_at = self._to_float(record.get("created_at"), 0.0)
            if created_at > 0 and (now_ts - created_at) >= threshold:
                count += 1
        return count

    def get_risk_summary(self) -> Dict:
        """
        Risk status summary.
        """
        denominator = max(1.0, self.config.max_total_exposure_usd)
        return {
            "halted": self._halted,
            "halt_reason": self._halt_reason,
            "halt_reason_code": self._halt_reason_code,
            "positions": len(self.positions),
            "max_positions": self.config.max_positions,
            "total_exposure": round(self.total_exposure, 2),
            "max_exposure": self.config.max_total_exposure_usd,
            "exposure_pct": round(self.total_exposure / denominator * 100, 1),
            "daily_pnl": round(_safe_float(self.daily_pnl, 0.0), 2),
            "daily_loss_limit": self.config.daily_loss_limit_usd,
            "daily_trades": self.daily_trade_count,
            "unrealized_pnl": round(self.total_unrealized_pnl, 2),
            "unrealized_loss_limit": round(_safe_float(self.config.unrealized_loss_limit_usd, 0.0), 2),
            "unresolved_closed_markets": len(self._unresolved_closed_markets),
            "live_orders_open": len([x for x in self.live_orders.values() if self._is_live_order_active(x)]),
            "live_orders_total": len(self.live_orders),
            "live_orders_blocking": len(
                [
                    x
                    for x in self.live_orders.values()
                    if self._is_live_order_active(x)
                    and (
                        self._normalize_live_order_status(x.get("status", "")) == "orphaned_pending_reconciliation"
                        or str(x.get("reconciliation_status", "")).strip().lower() == "orphaned_pending_reconciliation"
                    )
                ]
            ),
            "pending_live_notional": round(self.pending_live_notional, 2),
            "stale_live_orders": self.stale_live_order_count,
            "execution_intent_open": len(
                [x for x in self.execution_intents.values() if str(x.get("status", "")).strip().lower() in {"pending", "submitted"}]
            ),
            "execution_intents_total": len(self.execution_intents),
        }

    def print_status(self):
        """
        Print formatted risk status.
        """
        s = self.get_risk_summary()
        color = "red" if s["halted"] else ("yellow" if s["exposure_pct"] > 75 else "green")
        cprint(
            f"Risk: {s['positions']}/{s['max_positions']} positions | "
            f"${s['total_exposure']:.0f}/${s['max_exposure']:.0f} exposure "
            f"({s['exposure_pct']:.0f}%) | "
            f"Daily PnL: ${s['daily_pnl']:.2f} | "
            f"{'HALTED' if s['halted'] else 'Active'}",
            color,
        )
        if s["halted"] and s.get("halt_reason_code"):
            cprint(f"  Halt reason: {s['halt_reason_code']} :: {s['halt_reason']}", "red")


if __name__ == "__main__":
    rm = RiskManager()
    rm.print_status()

    can, reason = rm.can_trade("test_market_1", 50.0)
    print(f"\nCan trade $50 on test_market_1: {can} ({reason})")
